"""V2.8B/8 — compose the *real* review/recovery logic in a FAKE-ONLY sender rehearsal.

This module cannot send Shopify network requests. Its only transport is the
exact scripted in-memory fake type from V2.8B/5. It does NOT grant an operator
permission to mutate Shopify; fingerprint comparison is an evidence check only.

Stages: reload verified snapshot -> fresh operator review -> evidence fingerprint
match -> durable dispatch arm -> ONE fake mutation -> optional fake readback.
Any previous dispatch blocks the run, including timeouts or apparent success.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from supplier.batch.live_fake_sender import (
    ScriptedFakeShopifyTransport,
    SupplierLiveBatchFakeSender,
)
from supplier.batch.live_operator_review import (
    OperatorReviewStatus,
    review_saved_batch,
)
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive
from supplier.batch.live_recovery_models import RecoveryConflict, RecoveryState
from supplier.batch.live_response_policy import SimulatedResponseStatus

_SHA256_HEX = re.compile(r"[a-f0-9]{64}\Z")


class RehearsalStatus(str, Enum):
    INPUT_REJECTED = "INPUT_REJECTED"
    REVIEW_BLOCKED = "REVIEW_BLOCKED"
    REVIEW_FINGERPRINT_MISMATCH = "REVIEW_FINGERPRINT_MISMATCH"
    SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"
    SEND_ALREADY_ARMED = "SEND_ALREADY_ARMED"
    FAKE_ACK_NEEDS_READBACK = "FAKE_ACK_NEEDS_READBACK"
    FAKE_USER_ERRORS = "FAKE_USER_ERRORS"
    FAKE_UNKNOWN = "FAKE_UNKNOWN"


@dataclass(frozen=True, slots=True)
class RehearsalResult:
    operation_id: str
    status: RehearsalStatus
    review_status: OperatorReviewStatus | None = None
    response_status: SimulatedResponseStatus | None = None
    recovery_state: RecoveryState | None = None
    review_fingerprint: str | None = None
    fake_send_calls: int = 0
    journal_event_count: int = 0
    live_shopify_writes: int = 0
    automatic_retry_allowed: bool = False
    live_execution_allowed: bool = False
    inventory_verified_by_mutation: bool = False


class SupplierBatchSenderRehearsal:
    """Dry-run rehearsal with strict fake transport and no Shopify client."""

    def __init__(self, *, archive: ReadOnlyRecoveryArchive,
                 fake_sender: SupplierLiveBatchFakeSender) -> None:
        if type(archive) is not ReadOnlyRecoveryArchive:
            raise RecoveryConflict("rehearsal requires the verified read-only SQLite archive")
        if type(fake_sender) is not SupplierLiveBatchFakeSender:
            raise RecoveryConflict("rehearsal requires the strict V2.8B/5 fake sender")
        self._archive = archive
        self._sender = fake_sender

    def run_once(
        self, *, operation_id: str, expected_plan_fingerprint: str,
        expected_manifest_fingerprint: str, expected_location_id: str,
        expected_review_fingerprint: str, readback_port: Any,
        transport: ScriptedFakeShopifyTransport,
        post_send_readback_port: Any | None = None,
    ) -> RehearsalResult:
        # Reject real client objects BEFORE opening the archive or arming dispatch.
        if type(transport) is not ScriptedFakeShopifyTransport:
            raise RecoveryConflict("rehearsal accepts ONLY the exact in-memory scripted fake transport")
        if type(expected_review_fingerprint) is not str or _SHA256_HEX.fullmatch(expected_review_fingerprint) is None:
            return RehearsalResult(str(operation_id), RehearsalStatus.INPUT_REJECTED)
        if post_send_readback_port is not None and not callable(
            getattr(post_send_readback_port, "read_available", None)
        ):
            return RehearsalResult(str(operation_id), RehearsalStatus.INPUT_REJECTED)

        review = review_saved_batch(
            archive=self._archive,
            operation_id=operation_id,
            expected_plan_fingerprint=expected_plan_fingerprint,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
            expected_location_id=expected_location_id,
            readback_port=readback_port,
        )
        if review.status is not OperatorReviewStatus.REVIEW_READY:
            return RehearsalResult(
                str(operation_id), RehearsalStatus.REVIEW_BLOCKED,
                review_status=review.status,
            )
        if review.review_fingerprint is None:
            return RehearsalResult(
                operation_id, RehearsalStatus.REVIEW_BLOCKED,
                review_status=review.status,
            )
        # Comparison is NOT a signature, authentication or live-write approval.
        if not hmac.compare_digest(review.review_fingerprint, expected_review_fingerprint):
            return RehearsalResult(
                operation_id, RehearsalStatus.REVIEW_FINGERPRINT_MISMATCH,
                review_status=review.status, review_fingerprint=review.review_fingerprint,
            )

        # Check that the sender's actual durable database has the exact immutable
        # identity reviewed via read-only SQLite. Prevent accidental cross-DB sends.
        recovery = self._sender._recovery_service
        try:
            reviewed_snapshot, history = self._archive.load_verified(operation_id)
            sender_snapshot = recovery._recovery.load_snapshot(operation_id)
            if (
                history
                or reviewed_snapshot.payload_sha256 != sender_snapshot.payload_sha256
                or reviewed_snapshot.request_digest != sender_snapshot.request_digest
                or reviewed_snapshot.payload != sender_snapshot.payload
            ):
                return RehearsalResult(
                    operation_id, RehearsalStatus.SNAPSHOT_MISMATCH,
                    review_status=review.status,
                )
        except RecoveryConflict:
            return RehearsalResult(
                operation_id, RehearsalStatus.SNAPSHOT_MISMATCH,
                review_status=review.status,
            )

        # send_once performs an atomic, one-time DISPATCH_ARMED journal write
        # before invoking the fake transport. A second concurrent caller loses.
        try:
            sent = self._sender.send_once(operation_id=operation_id, transport=transport)
        except RecoveryConflict:
            # A conflict *after* a fake send could be a receipt-integrity error.
            # Do not disguise such a failure as a harmless concurrent arm.
            if transport.calls != 0:
                raise
            return RehearsalResult(
                operation_id, RehearsalStatus.SEND_ALREADY_ARMED,
                review_status=review.status,
            )
        # Unexpected DB/disk failures intentionally propagate: never report
        # success when receipt persistence is untrusted. The arm is still durable.
        if post_send_readback_port is not None:
            recovery.observe_current_inventory(
                operation_id=operation_id, readback_port=post_send_readback_port,
            )
        decision = recovery.decision(operation_id=operation_id)
        statuses = {
            SimulatedResponseStatus.ACKNOWLEDGED_NEEDS_READBACK: RehearsalStatus.FAKE_ACK_NEEDS_READBACK,
            SimulatedResponseStatus.USER_ERRORS_REQUIRE_REVIEW: RehearsalStatus.FAKE_USER_ERRORS,
            SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW: RehearsalStatus.FAKE_UNKNOWN,
        }
        return RehearsalResult(
            operation_id=operation_id,
            status=statuses[sent.assessment.status],
            review_status=review.status,
            response_status=sent.assessment.status,
            recovery_state=decision.state,
            review_fingerprint=review.review_fingerprint,
            fake_send_calls=transport.calls,
            journal_event_count=decision.event_count,
        )
