"""V2.8B/7 — read-only, fail-closed review of a prepared two-item batch.

NO network mutation, no SQLite writes, no dispatch authorization, no retry.
A positive review is an operator CHECKPOINT, not permission to send inventory.
The future live sender must perform its own last-moment checks and durable arm.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive
from supplier.batch.live_readonly_inspection import (
    InspectionStatus, inspect_saved_operation,
)
from supplier.batch.live_request_contract import LOCATION_GID_RE

_HASH = re.compile(r"[0-9a-f]{64}\Z")


class OperatorReviewStatus(str, Enum):
    REVIEW_READY = "REVIEW_READY"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    DISPATCH_HISTORY = "DISPATCH_HISTORY"
    INVENTORY_STALE = "INVENTORY_STALE"
    INSPECTION_BLOCKED = "INSPECTION_BLOCKED"
    ARCHIVE_UNTRUSTED = "ARCHIVE_UNTRUSTED"
    RECORD_CHANGED_DURING_REVIEW = "RECORD_CHANGED_DURING_REVIEW"
    POLICY_REJECTED = "POLICY_REJECTED"


@dataclass(frozen=True, slots=True)
class OperatorReviewReport:
    operation_id: str
    status: OperatorReviewStatus
    reason_code: str
    read_count: int = 0
    review_fingerprint: str | None = None
    verified_items: tuple[tuple[str, int, int, int], ...] = ()
    can_continue_to_operator_review: bool = False
    live_execution_allowed: bool = False
    automatic_retry_allowed: bool = False
    human_review_required: bool = True


def _deny(operation_id: str, status: OperatorReviewStatus, *, reads: int = 0) -> OperatorReviewReport:
    return OperatorReviewReport(operation_id, status, status.value, read_count=reads)


def review_saved_batch(
    *, archive: ReadOnlyRecoveryArchive, operation_id: str,
    expected_plan_fingerprint: str, expected_manifest_fingerprint: str,
    expected_location_id: str, readback_port: Any,
) -> OperatorReviewReport:
    """Review a verified SQLite operation against two fresh quantity reads.

    Expected fingerprints must come from a separate current operator workflow.
    A fingerprint is NOT an approval or an authentication signature.
    A last-moment Shopify CAS check remains essential even after REVIEW_READY.
    """
    if not isinstance(archive, ReadOnlyRecoveryArchive):
        return _deny(str(operation_id), OperatorReviewStatus.ARCHIVE_UNTRUSTED)
    if (
        type(expected_plan_fingerprint) is not str or _HASH.fullmatch(expected_plan_fingerprint) is None
        or type(expected_manifest_fingerprint) is not str or _HASH.fullmatch(expected_manifest_fingerprint) is None
        or type(expected_location_id) is not str or LOCATION_GID_RE.fullmatch(expected_location_id) is None
        or type(operation_id) is not str or not callable(getattr(readback_port, "read_available", None))
    ):
        return _deny(str(operation_id), OperatorReviewStatus.POLICY_REJECTED)

    try:
        snapshot, journal_before = archive.load_verified(operation_id)
    except Exception:
        return _deny(operation_id, OperatorReviewStatus.ARCHIVE_UNTRUSTED)

    payload = snapshot.payload
    if (
        payload.get("plan_fingerprint") != expected_plan_fingerprint
        or payload.get("manifest_fingerprint") != expected_manifest_fingerprint
        or payload.get("location_id") != expected_location_id
    ):
        return _deny(operation_id, OperatorReviewStatus.IDENTITY_MISMATCH)
    if journal_before:
        # Any armed operation must be investigated by the V2.8B/6 recovery
        # inspector. Observing a matching target must NEVER re-enable sending.
        return _deny(operation_id, OperatorReviewStatus.DISPATCH_HISTORY)

    # Defense in depth: verify the historic contract's small-delta policy.
    try:
        quantities = payload["variables"]["input"]["quantities"]
        deltas = [abs(t["quantity"] - t["changeFromQuantity"]) for t in quantities]
        if (
            len(quantities) != 2
            or any(type(t["quantity"]) is not int or type(t["changeFromQuantity"]) is not int for t in quantities)
            or any(not 1 <= delta <= 2 for delta in deltas)
            or sum(deltas) > 3
        ):
            return _deny(operation_id, OperatorReviewStatus.POLICY_REJECTED)
    except (KeyError, TypeError, ValueError):
        return _deny(operation_id, OperatorReviewStatus.POLICY_REJECTED)

    try:
        inspected = inspect_saved_operation(
            archive=archive, operation_id=operation_id,
            readback_port=readback_port,
        )
    except Exception:
        return _deny(operation_id, OperatorReviewStatus.INSPECTION_BLOCKED)

    if inspected.dispatch_event_count != 0:
        return _deny(operation_id, OperatorReviewStatus.DISPATCH_HISTORY, reads=inspected.successful_reads)

    # Check the archive again after the external reads to detect a dispatch or
    # snapshot alteration occurring while review was underway. It is still only
    # a review; no atomic Shopify+SQLite transaction exists across this gap.
    try:
        snapshot_after, journal_after = archive.load_verified(operation_id)
    except Exception:
        return _deny(operation_id, OperatorReviewStatus.ARCHIVE_UNTRUSTED, reads=inspected.successful_reads)
    if (
        journal_after or snapshot.payload_sha256 != snapshot_after.payload_sha256
        or snapshot.request_digest != snapshot_after.request_digest
    ):
        return _deny(operation_id, OperatorReviewStatus.RECORD_CHANGED_DURING_REVIEW, reads=inspected.successful_reads)

    if inspected.status == InspectionStatus.STALE:
        return _deny(operation_id, OperatorReviewStatus.INVENTORY_STALE, reads=inspected.successful_reads)
    if inspected.status != InspectionStatus.BASELINES_MATCH or inspected.successful_reads != 2:
        return _deny(operation_id, OperatorReviewStatus.INSPECTION_BLOCKED, reads=inspected.successful_reads)

    items = tuple((i.sku, i.baseline, i.observed, i.proposed) for i in inspected.items)
    if len(items) != 2 or any(before != actual for _, before, actual, _ in items):
        return _deny(operation_id, OperatorReviewStatus.INSPECTION_BLOCKED, reads=inspected.successful_reads)

    canonical = json.dumps({
        "operation_id": operation_id,
        "snapshot_sha256": snapshot.payload_sha256,
        "request_digest": snapshot.request_digest,
        "plan_fingerprint": expected_plan_fingerprint,
        "manifest_fingerprint": expected_manifest_fingerprint,
        "location_id": expected_location_id,
        "items": items,
        "status": OperatorReviewStatus.REVIEW_READY.value,
    }, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return OperatorReviewReport(
        operation_id=operation_id, status=OperatorReviewStatus.REVIEW_READY,
        reason_code="TWO_READS_MATCH_SAVED_CAS_BASELINES",
        read_count=2, review_fingerprint=fingerprint,
        verified_items=items, can_continue_to_operator_review=True,
    )
