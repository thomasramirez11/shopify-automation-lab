"""V2.8B/9: conservative, strictly READ-ONLY live-operation risk assessment.

This is *not* a live sender and cannot grant write authorization.  A positive
result means only that a controlled TEST operation may proceed to a separate
human/architecture review.  In particular, the caller-provided store name is
not proof of an authenticated Shopify session; a real shop-identity query must
be integrated before any production sender is enabled.
"""
from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from supplier.batch.live_operator_review import (
    OperatorReviewStatus, review_saved_batch,
)
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive
from supplier.batch.live_request_contract import (
    INVENTORY_GID_RE, INVENTORY_SET_QUANTITIES, LOCATION_GID_RE,
    MAX_ABS_DELTA_PER_ITEM, MAX_ITEMS, MAX_TOTAL_ABS_DELTA,
)

_SHOP = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,59}[a-z0-9])?\.myshopify\.com\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")


class RiskStatus(str, Enum):
    REVIEW_OK_FOR_FURTHER_DESIGN = "REVIEW_OK_FOR_FURTHER_DESIGN"
    INVALID_POLICY = "INVALID_POLICY"
    STORE_MISMATCH = "STORE_MISMATCH"
    SOURCE_NOT_ALLOWED = "SOURCE_NOT_ALLOWED"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    PREVIOUS_DISPATCH = "PREVIOUS_DISPATCH"
    REVIEW_BLOCKED = "REVIEW_BLOCKED"
    TARGET_MISMATCH = "TARGET_MISMATCH"
    RISK_BUDGET_EXCEEDED = "RISK_BUDGET_EXCEEDED"
    ARCHIVE_UNTRUSTED = "ARCHIVE_UNTRUSTED"


@dataclass(frozen=True, slots=True)
class ControlledTestBudget:
    """Pinned scope for one *synthetic* two-item test proposal.

    The store and item IDs must be separately confirmed by the eventual real
    Shopify adapter. The budget itself never authenticates an operator.
    """
    store_domain: str
    location_id: str
    sku_inventory_items: tuple[tuple[str, str], tuple[str, str]]
    max_delta_per_item: int = 2
    max_total_delta: int = 3
    max_target_quantity: int = 100


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    operation_id: str
    status: RiskStatus
    reason: str
    successful_inventory_reads: int = 0
    reviewed_fingerprint: str | None = None
    total_abs_delta: int = 0
    can_continue_to_operator_review: bool = False
    live_execution_allowed: bool = False
    automatic_retry_allowed: bool = False


def _deny(operation_id: str, status: RiskStatus, *, reads: int = 0) -> RiskAssessment:
    return RiskAssessment(operation_id=operation_id, status=status,
                          reason=status.value, successful_inventory_reads=reads)


def _valid_budget(value: ControlledTestBudget) -> bool:
    if type(value) is not ControlledTestBudget or type(value.store_domain) is not str or _SHOP.fullmatch(value.store_domain) is None:
        return False
    if type(value.location_id) is not str or LOCATION_GID_RE.fullmatch(value.location_id) is None:
        return False
    if not isinstance(value.sku_inventory_items, tuple) or len(value.sku_inventory_items) != MAX_ITEMS:
        return False
    pairs = value.sku_inventory_items
    for pair in pairs:
        if type(pair) is not tuple or len(pair) != 2:
            return False
        sku, item = pair
        if type(sku) is not str or not sku or sku != sku.strip() or type(item) is not str or INVENTORY_GID_RE.fullmatch(item) is None:
            return False
    if len({p[0] for p in pairs}) != MAX_ITEMS or len({p[1] for p in pairs}) != MAX_ITEMS:
        return False
    return (
        type(value.max_delta_per_item) is int and 1 <= value.max_delta_per_item <= MAX_ABS_DELTA_PER_ITEM
        and type(value.max_total_delta) is int and 1 <= value.max_total_delta <= MAX_TOTAL_ABS_DELTA
        and type(value.max_target_quantity) is int and 1 <= value.max_target_quantity <= 1000
    )


def assess_test_operation(
    *, archive: ReadOnlyRecoveryArchive, operation_id: str,
    expected_plan_fingerprint: str, expected_manifest_fingerprint: str,
    observed_store_domain: str, proposal_source: str,
    budget: ControlledTestBudget, readback_port: Any,
) -> RiskAssessment:
    """Run fresh operator review and enforce pinned risk constraints.

    `observed_store_domain` must ultimately be populated from an authenticated
    `shop { myshopifyDomain }` query; this offline assessment cannot attest it.
    `proposal_source` is deliberately limited to a CONTROLLED_TEST proposal.
    Real supplier-feed authority is a separate future validation task.
    """
    if not _valid_budget(budget):
        return _deny(str(operation_id), RiskStatus.INVALID_POLICY)
    if type(observed_store_domain) is not str or _SHOP.fullmatch(observed_store_domain) is None:
        return _deny(str(operation_id), RiskStatus.STORE_MISMATCH)
    if not hmac.compare_digest(observed_store_domain, budget.store_domain):
        return _deny(str(operation_id), RiskStatus.STORE_MISMATCH)
    if proposal_source != "CONTROLLED_TEST_SYNTHETIC":
        return _deny(str(operation_id), RiskStatus.SOURCE_NOT_ALLOWED)
    if (
        type(expected_plan_fingerprint) is not str or _SHA256.fullmatch(expected_plan_fingerprint) is None
        or type(expected_manifest_fingerprint) is not str or _SHA256.fullmatch(expected_manifest_fingerprint) is None
    ):
        return _deny(str(operation_id), RiskStatus.IDENTITY_MISMATCH)

    # This reuses the V2.8B/7 real review function and its read-only archive.
    # It performs two *fresh* inventory reads through an injected port.
    review = review_saved_batch(
        archive=archive, operation_id=operation_id,
        expected_plan_fingerprint=expected_plan_fingerprint,
        expected_manifest_fingerprint=expected_manifest_fingerprint,
        expected_location_id=budget.location_id,
        readback_port=readback_port,
    )
    if review.status == OperatorReviewStatus.DISPATCH_HISTORY:
        return _deny(str(operation_id), RiskStatus.PREVIOUS_DISPATCH, reads=review.read_count)
    if review.status is not OperatorReviewStatus.REVIEW_READY:
        return _deny(str(operation_id), RiskStatus.REVIEW_BLOCKED, reads=review.read_count)
    if (
        review.read_count != MAX_ITEMS or not review.can_continue_to_operator_review
        or review.live_execution_allowed or review.automatic_retry_allowed
        or type(review.review_fingerprint) is not str
        or _SHA256.fullmatch(review.review_fingerprint) is None
    ):
        return _deny(str(operation_id), RiskStatus.REVIEW_BLOCKED, reads=review.read_count)

    try:
        snapshot, events = archive.load_verified(operation_id)
        payload = snapshot.payload
        input_data = payload["variables"]["input"]
        quantities = input_data["quantities"]
        skus = payload["skus"]
        if events:
            return _deny(str(operation_id), RiskStatus.PREVIOUS_DISPATCH, reads=review.read_count)
        if (
            payload["operation_id"] != operation_id
            or payload["plan_fingerprint"] != expected_plan_fingerprint
            or payload["manifest_fingerprint"] != expected_manifest_fingerprint
            or payload["location_id"] != budget.location_id
            or payload["query"] != INVENTORY_SET_QUANTITIES
            or payload["variables"]["idempotencyKey"] != operation_id
            or input_data["name"] != "available"
            or len(quantities) != MAX_ITEMS or len(skus) != MAX_ITEMS
        ):
            return _deny(str(operation_id), RiskStatus.IDENTITY_MISMATCH, reads=review.read_count)
        actual_pairs = tuple((sku, q["inventoryItemId"]) for sku, q in zip(skus, quantities))
        if set(actual_pairs) != set(budget.sku_inventory_items):
            return _deny(str(operation_id), RiskStatus.TARGET_MISMATCH, reads=review.read_count)
        if len({item for _, item in actual_pairs}) != MAX_ITEMS:
            return _deny(str(operation_id), RiskStatus.TARGET_MISMATCH, reads=review.read_count)
        report_items = {sku: (baseline, observed, proposed)
                        for sku, baseline, observed, proposed in review.verified_items}
        if len(report_items) != MAX_ITEMS or set(report_items) != {pair[0] for pair in actual_pairs}:
            return _deny(str(operation_id), RiskStatus.TARGET_MISMATCH, reads=review.read_count)

        total = 0
        for sku, quantity in zip(skus, quantities):
            before, after = quantity["changeFromQuantity"], quantity["quantity"]
            if (
                type(before) is not int or type(after) is not int
                or before < 0 or after < 0
                or quantity["locationId"] != budget.location_id
                or report_items[sku] != (before, before, after)
            ):
                return _deny(str(operation_id), RiskStatus.TARGET_MISMATCH, reads=review.read_count)
            delta = abs(after - before)
            if not 1 <= delta <= budget.max_delta_per_item or after > budget.max_target_quantity:
                return _deny(str(operation_id), RiskStatus.RISK_BUDGET_EXCEEDED, reads=review.read_count)
            total += delta
        if total > budget.max_total_delta:
            return _deny(str(operation_id), RiskStatus.RISK_BUDGET_EXCEEDED, reads=review.read_count)

        # Reload after external inspection and risk validation. Still no
        # atomicity with Shopify: the sender must do a final CAS-protected send.
        again, events_after = archive.load_verified(operation_id)
        if events_after:
            return _deny(str(operation_id), RiskStatus.PREVIOUS_DISPATCH, reads=review.read_count)
        if again.payload_sha256 != snapshot.payload_sha256 or again.request_digest != snapshot.request_digest:
            return _deny(str(operation_id), RiskStatus.ARCHIVE_UNTRUSTED, reads=review.read_count)
    except Exception:
        # Fail closed without logging raw credentials or response bodies.
        return _deny(str(operation_id), RiskStatus.ARCHIVE_UNTRUSTED, reads=review.read_count)

    return RiskAssessment(
        operation_id=operation_id, status=RiskStatus.REVIEW_OK_FOR_FURTHER_DESIGN,
        reason="CONTROLLED_TEST_SCOPE_AND_BUDGET_VERIFIED_OFFLINE",
        successful_inventory_reads=review.read_count,
        reviewed_fingerprint=review.review_fingerprint,
        total_abs_delta=total,
        can_continue_to_operator_review=True,
    )
