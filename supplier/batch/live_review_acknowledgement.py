"""V2.8B/10: authenticated store identity + human REVIEW acknowledgment.

IMPORTANT: an acknowledgment is NOT operator authentication or a Shopify
mutation authorization. All outcomes leave LIVE EXECUTION DISABLED. This is
only a safety gate for further engineering/design review of the synthetic
controlled two-item test proposal.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from supplier.batch.live_risk_budget import (
    ControlledTestBudget, RiskStatus, assess_test_operation,
)
from supplier.batch.live_store_identity import (
    SHOP_GID_RE, ShopifyStoreIdentityReadOnly, StoreIdentityRejected,
)


class ReviewAckStatus(str, Enum):
    IDENTITY_UNAVAILABLE = "IDENTITY_UNAVAILABLE"
    SHOP_ID_MISMATCH = "SHOP_ID_MISMATCH"
    STORE_MISMATCH = "STORE_MISMATCH"
    REVIEW_BLOCKED = "REVIEW_BLOCKED"
    ACKNOWLEDGEMENT_REQUIRED = "ACKNOWLEDGEMENT_REQUIRED"
    ACKNOWLEDGEMENT_MISMATCH = "ACKNOWLEDGEMENT_MISMATCH"
    ACKNOWLEDGED_FOR_FURTHER_REVIEW = "ACKNOWLEDGED_FOR_FURTHER_REVIEW"


@dataclass(frozen=True, slots=True)
class ReviewAckResult:
    status: ReviewAckStatus
    shop_id: str | None = None
    store_domain: str | None = None
    operation_id: str | None = None
    review_fingerprint: str | None = None
    expected_acknowledgement: str | None = None
    successful_inventory_reads: int = 0
    can_continue_to_operator_review: bool = False
    live_execution_allowed: bool = False
    automatic_retry_allowed: bool = False
    operator_authenticated: bool = False


def _acknowledgement(*, shop_id: str, store_domain: str, operation_id: str,
                     review_fingerprint: str, budget: ControlledTestBudget) -> str:
    """Bind a human-readable acknowledgement to exact reviewed evidence."""
    encoded = json.dumps({
        "kind": "V2.8B/10_REVIEW_ONLY",
        "shop_id": shop_id,
        "store_domain": store_domain,
        "operation_id": operation_id,
        "review_fingerprint": review_fingerprint,
        "location_id": budget.location_id,
        "targets": budget.sku_inventory_items,
        "limits": (budget.max_delta_per_item, budget.max_total_delta,
                   budget.max_target_quantity),
    }, sort_keys=True, separators=(",", ":"))
    return "ACK-REVIEW-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def review_with_authenticated_identity(
    *, shop_identity: ShopifyStoreIdentityReadOnly,
    expected_shop_id: str, archive: Any, operation_id: str,
    expected_plan_fingerprint: str, expected_manifest_fingerprint: str,
    proposal_source: str, budget: ControlledTestBudget, readback_port: Any,
    operator_acknowledgement: str | None = None,
) -> ReviewAckResult:
    """Read authenticated shop identity, then risk-review two fresh quantities.

    On every invocation, even when an ACK is supplied, fresh Shopify identity
    and fresh inventory evidence must be gathered. This function is *never*
    permitted to arm a dispatch or send a mutation, even after acknowledgment.
    """
    if not isinstance(shop_identity, ShopifyStoreIdentityReadOnly):
        return ReviewAckResult(ReviewAckStatus.IDENTITY_UNAVAILABLE)
    if type(expected_shop_id) is not str or SHOP_GID_RE.fullmatch(expected_shop_id) is None:
        return ReviewAckResult(ReviewAckStatus.SHOP_ID_MISMATCH)
    try:
        identity = shop_identity.read()
    except StoreIdentityRejected:
        return ReviewAckResult(ReviewAckStatus.IDENTITY_UNAVAILABLE)
    if not hmac.compare_digest(identity.shop_id, expected_shop_id):
        return ReviewAckResult(ReviewAckStatus.SHOP_ID_MISMATCH,
                               shop_id=identity.shop_id, store_domain=identity.domain)
    if type(budget) is not ControlledTestBudget or budget.store_domain != identity.domain:
        return ReviewAckResult(ReviewAckStatus.STORE_MISMATCH,
                               shop_id=identity.shop_id, store_domain=identity.domain)

    # Risk assessment must derive observed_store_domain from the authenticated
    # Shopify identity, never from a caller-supplied command-line string.
    try:
        risk = assess_test_operation(
            archive=archive, operation_id=operation_id,
            expected_plan_fingerprint=expected_plan_fingerprint,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
            observed_store_domain=identity.domain,
            proposal_source=proposal_source, budget=budget,
            readback_port=readback_port,
        )
    except Exception:
        return ReviewAckResult(ReviewAckStatus.REVIEW_BLOCKED, shop_id=identity.shop_id,
                               store_domain=identity.domain)
    if (
        risk.status is not RiskStatus.REVIEW_OK_FOR_FURTHER_DESIGN
        or not risk.reviewed_fingerprint
        or risk.successful_inventory_reads != 2
        or risk.live_execution_allowed or risk.automatic_retry_allowed
    ):
        return ReviewAckResult(ReviewAckStatus.REVIEW_BLOCKED, shop_id=identity.shop_id,
                               store_domain=identity.domain,
                               operation_id=str(operation_id),
                               successful_inventory_reads=risk.successful_inventory_reads)
    phrase = _acknowledgement(
        shop_id=identity.shop_id, store_domain=identity.domain,
        operation_id=operation_id, review_fingerprint=risk.reviewed_fingerprint,
        budget=budget,
    )
    common = dict(shop_id=identity.shop_id, store_domain=identity.domain,
                  operation_id=operation_id, review_fingerprint=risk.reviewed_fingerprint,
                  expected_acknowledgement=phrase,
                  successful_inventory_reads=risk.successful_inventory_reads)
    if operator_acknowledgement is None:
        return ReviewAckResult(ReviewAckStatus.ACKNOWLEDGEMENT_REQUIRED, **common)
    if (
        type(operator_acknowledgement) is not str
        or not hmac.compare_digest(operator_acknowledgement, phrase)
    ):
        return ReviewAckResult(ReviewAckStatus.ACKNOWLEDGEMENT_MISMATCH, **common)
    return ReviewAckResult(
        ReviewAckStatus.ACKNOWLEDGED_FOR_FURTHER_REVIEW,
        can_continue_to_operator_review=True, **common,
    )
