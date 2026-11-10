from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from supplier.decision.models import (
    SupplierSyncDecision,
    SyncDecisionStatus,
)
from supplier.plan.models import (
    SupplierSyncPlan,
    SupplierSyncPlanError,
    SupplierSyncPlanItem,
    SyncPlanAction,
    SyncPlanMode,
)


def build_dry_run_sync_plan(
    decisions: Iterable[
        SupplierSyncDecision
    ],
) -> SupplierSyncPlan:
    """
    Convert policy decisions into a deterministic DRY_RUN sync plan.

    Safety guarantees:
    - no Shopify API calls
    - no SQLite writes
    - REVIEW/BLOCKED/NO_ACTION never become mutations
    - only ELIGIBLE decisions may propose SET_INVENTORY
    """

    items = tuple(
        _build_item(
            decision
        )
        for decision in decisions
    )

    _validate_unique_shopify_targets(
        items
    )

    fingerprint = (
        _build_fingerprint(
            items
        )
    )

    return SupplierSyncPlan(
        mode=SyncPlanMode.DRY_RUN,
        items=items,
        fingerprint=fingerprint,
    )


def _build_item(
    decision: SupplierSyncDecision,
) -> SupplierSyncPlanItem:
    if (
        decision.status
        == SyncDecisionStatus.ELIGIBLE
    ):
        if (
            decision.proposed_inventory_quantity
            is None
        ):
            raise SupplierSyncPlanError(
                "ELIGIBLE decision must include "
                "proposed_inventory_quantity."
            )

        if (
            decision.proposed_inventory_quantity
            < 0
        ):
            raise SupplierSyncPlanError(
                "proposed_inventory_quantity cannot be negative."
            )

        action = (
            SyncPlanAction.SET_INVENTORY
        )

    else:
        if (
            decision.proposed_inventory_quantity
            is not None
        ):
            raise SupplierSyncPlanError(
                "Only ELIGIBLE decisions may include "
                "proposed_inventory_quantity."
            )

        action = (
            SyncPlanAction.NONE
        )

    return SupplierSyncPlanItem(
        supplier_code=(
            decision.supplier_code
        ),
        supplier_sku=(
            decision.supplier_sku
        ),
        shopify_variant_id=(
            decision.shopify_variant_id
        ),
        shopify_sku=(
            decision.shopify_sku
        ),
        decision_status=(
            decision.status
        ),
        decision_reason=(
            decision.reason
        ),
        action=action,
        current_inventory_quantity=(
            decision.current_inventory_quantity
        ),
        proposed_inventory_quantity=(
            decision.proposed_inventory_quantity
        ),
        inventory_delta=(
            decision.inventory_delta
        ),
    )


def _validate_unique_shopify_targets(
    items: tuple[
        SupplierSyncPlanItem,
        ...,
    ],
) -> None:
    seen: set[str] = set()

    for item in items:
        if (
            item.shopify_variant_id
            in seen
        ):
            raise SupplierSyncPlanError(
                "Dry-run plan contains duplicate Shopify variant target: "
                f"{item.shopify_variant_id}"
            )

        seen.add(
            item.shopify_variant_id
        )


def _build_fingerprint(
    items: tuple[
        SupplierSyncPlanItem,
        ...,
    ],
) -> str:
    canonical_items = [
        {
            "supplier_code":
                item.supplier_code,
            "supplier_sku":
                item.supplier_sku,
            "shopify_variant_id":
                item.shopify_variant_id,
            "shopify_sku":
                item.shopify_sku,
            "decision_status":
                item.decision_status.value,
            "decision_reason":
                item.decision_reason.value,
            "action":
                item.action.value,
            "current_inventory_quantity":
                item.current_inventory_quantity,
            "proposed_inventory_quantity":
                item.proposed_inventory_quantity,
            "inventory_delta":
                item.inventory_delta,
        }
        for item in items
    ]

    canonical_json = json.dumps(
        canonical_items,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical_json.encode(
            "utf-8"
        )
    ).hexdigest()
