from __future__ import annotations

from supplier.comparison.models import (
    ComparisonStatus,
    SupplierShopifyComparison,
)
from supplier.decision.models import (
    InventorySyncPolicy,
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)


def evaluate_supplier_sync_decision(
    *,
    comparison: SupplierShopifyComparison,
    policy: InventorySyncPolicy,
) -> SupplierSyncDecision:
    """
    Convert one comparison result into a safety-oriented sync recommendation.

    IMPORTANT:
    This function does not write to Shopify or SQLite.
    It only decides what SHOULD happen next.
    """

    if (
        comparison.status
        == ComparisonStatus.MATCH
    ):
        return _decision(
            comparison=comparison,
            status=(
                SyncDecisionStatus.NO_ACTION
            ),
            reason=(
                SyncDecisionReason.ALREADY_MATCHED
            ),
            proposed_inventory_quantity=None,
        )

    if (
        comparison.status
        == ComparisonStatus.MISSING_SUPPLIER_PRODUCT
    ):
        return _decision(
            comparison=comparison,
            status=(
                SyncDecisionStatus.BLOCKED
            ),
            reason=(
                SyncDecisionReason.SUPPLIER_PRODUCT_MISSING
            ),
            proposed_inventory_quantity=None,
        )

    if (
        comparison.status
        == ComparisonStatus.MISSING_SHOPIFY_VARIANT
    ):
        return _decision(
            comparison=comparison,
            status=(
                SyncDecisionStatus.BLOCKED
            ),
            reason=(
                SyncDecisionReason.SHOPIFY_VARIANT_MISSING
            ),
            proposed_inventory_quantity=None,
        )

    if (
        comparison.status
        == ComparisonStatus.COST_MISMATCH
    ):
        return _decision(
            comparison=comparison,
            status=(
                SyncDecisionStatus.REVIEW
            ),
            reason=(
                SyncDecisionReason.COST_CHANGE_REQUIRES_REVIEW
            ),
            proposed_inventory_quantity=None,
        )

    if (
        comparison.status
        == ComparisonStatus.STOCK_AND_COST_MISMATCH
    ):
        return _decision(
            comparison=comparison,
            status=(
                SyncDecisionStatus.REVIEW
            ),
            reason=(
                SyncDecisionReason.STOCK_AND_COST_CHANGE_REQUIRES_REVIEW
            ),
            proposed_inventory_quantity=None,
        )

    # At this point the only supported status is STOCK_MISMATCH.
    inventory_delta = (
        comparison.stock_difference
    )

    supplier_inventory = (
        comparison.supplier_stock
    )

    if (
        inventory_delta is None
        or supplier_inventory is None
    ):
        raise ValueError(
            "STOCK_MISMATCH comparison must contain stock values."
        )

    if (
        abs(inventory_delta)
        > policy.max_inventory_delta
    ):
        return _decision(
            comparison=comparison,
            status=(
                SyncDecisionStatus.REVIEW
            ),
            reason=(
                SyncDecisionReason.INVENTORY_CHANGE_EXCEEDS_LIMIT
            ),
            proposed_inventory_quantity=None,
        )

    return _decision(
        comparison=comparison,
        status=(
            SyncDecisionStatus.ELIGIBLE
        ),
        reason=(
            SyncDecisionReason.INVENTORY_MISMATCH_WITHIN_LIMIT
        ),
        proposed_inventory_quantity=(
            supplier_inventory
        ),
    )


def _decision(
    *,
    comparison: SupplierShopifyComparison,
    status: SyncDecisionStatus,
    reason: SyncDecisionReason,
    proposed_inventory_quantity: int | None,
) -> SupplierSyncDecision:
    return SupplierSyncDecision(
        supplier_code=(
            comparison.supplier_code
        ),
        supplier_sku=(
            comparison.supplier_sku
        ),
        shopify_variant_id=(
            comparison.shopify_variant_id
        ),
        shopify_sku=(
            comparison.shopify_sku
        ),
        status=status,
        reason=reason,
        current_inventory_quantity=(
            comparison.shopify_stock
        ),
        supplier_inventory_quantity=(
            comparison.supplier_stock
        ),
        inventory_delta=(
            comparison.stock_difference
        ),
        proposed_inventory_quantity=(
            proposed_inventory_quantity
        ),
    )
