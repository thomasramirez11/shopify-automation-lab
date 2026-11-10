from decimal import Decimal

import pytest

from supplier.comparison.models import (
    ComparisonStatus,
    SupplierShopifyComparison,
)
from supplier.decision.models import (
    InventorySyncPolicy,
    SupplierSyncPolicyError,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.decision.policy import (
    evaluate_supplier_sync_decision,
)


def comparison(
    *,
    status=ComparisonStatus.MATCH,
    supplier_stock=10,
    shopify_stock=10,
    stock_difference=0,
    supplier_cost=Decimal("4.25"),
    stored_cost=Decimal("4.25"),
    cost_difference=Decimal("0.00"),
):
    return SupplierShopifyComparison(
        supplier_code="demo_supplier",
        supplier_sku="SUP-CAP-001",
        shopify_variant_id=(
            "gid://shopify/ProductVariant/56166258147700"
        ),
        shopify_sku="AUTO-Cap-001",
        status=status,
        supplier_stock=supplier_stock,
        shopify_stock=shopify_stock,
        stock_difference=stock_difference,
        supplier_cost=supplier_cost,
        stored_cost=stored_cost,
        cost_difference=cost_difference,
    )


def test_policy_defaults_to_fifty_item_delta():
    policy = InventorySyncPolicy()

    assert (
        policy.max_inventory_delta
        == 50
    )


def test_policy_rejects_negative_limit():
    with pytest.raises(
        SupplierSyncPolicyError,
        match="cannot be negative",
    ):
        InventorySyncPolicy(
            max_inventory_delta=-1
        )


def test_policy_rejects_non_integer_limit():
    with pytest.raises(
        SupplierSyncPolicyError,
        match="must be an integer",
    ):
        InventorySyncPolicy(
            max_inventory_delta=1.5
        )


def test_match_becomes_no_action():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(),
            policy=InventorySyncPolicy(),
        )
    )

    assert (
        result.status
        == SyncDecisionStatus.NO_ACTION
    )
    assert (
        result.reason
        == SyncDecisionReason.ALREADY_MATCHED
    )
    assert (
        result.proposed_inventory_quantity
        is None
    )


def test_small_positive_stock_delta_is_eligible():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(
                status=(
                    ComparisonStatus.STOCK_MISMATCH
                ),
                supplier_stock=25,
                shopify_stock=1,
                stock_difference=24,
            ),
            policy=InventorySyncPolicy(
                max_inventory_delta=50
            ),
        )
    )

    assert (
        result.status
        == SyncDecisionStatus.ELIGIBLE
    )
    assert (
        result.proposed_inventory_quantity
        == 25
    )
    assert result.is_eligible is True


def test_small_negative_stock_delta_is_eligible():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(
                status=(
                    ComparisonStatus.STOCK_MISMATCH
                ),
                supplier_stock=2,
                shopify_stock=10,
                stock_difference=-8,
            ),
            policy=InventorySyncPolicy(
                max_inventory_delta=50
            ),
        )
    )

    assert (
        result.status
        == SyncDecisionStatus.ELIGIBLE
    )
    assert (
        result.proposed_inventory_quantity
        == 2
    )


def test_delta_equal_to_limit_is_eligible():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(
                status=(
                    ComparisonStatus.STOCK_MISMATCH
                ),
                supplier_stock=60,
                shopify_stock=10,
                stock_difference=50,
            ),
            policy=InventorySyncPolicy(
                max_inventory_delta=50
            ),
        )
    )

    assert (
        result.status
        == SyncDecisionStatus.ELIGIBLE
    )


def test_delta_above_limit_requires_review():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(
                status=(
                    ComparisonStatus.STOCK_MISMATCH
                ),
                supplier_stock=61,
                shopify_stock=10,
                stock_difference=51,
            ),
            policy=InventorySyncPolicy(
                max_inventory_delta=50
            ),
        )
    )

    assert (
        result.status
        == SyncDecisionStatus.REVIEW
    )
    assert (
        result.reason
        == SyncDecisionReason.INVENTORY_CHANGE_EXCEEDS_LIMIT
    )
    assert (
        result.proposed_inventory_quantity
        is None
    )


def test_cost_mismatch_requires_review():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(
                status=(
                    ComparisonStatus.COST_MISMATCH
                ),
                cost_difference=(
                    Decimal("0.75")
                ),
            ),
            policy=InventorySyncPolicy(),
        )
    )

    assert (
        result.status
        == SyncDecisionStatus.REVIEW
    )
    assert (
        result.reason
        == SyncDecisionReason.COST_CHANGE_REQUIRES_REVIEW
    )


def test_stock_and_cost_mismatch_requires_review():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(
                status=(
                    ComparisonStatus.STOCK_AND_COST_MISMATCH
                ),
                supplier_stock=25,
                shopify_stock=1,
                stock_difference=24,
                cost_difference=(
                    Decimal("0.75")
                ),
            ),
            policy=InventorySyncPolicy(),
        )
    )

    assert (
        result.status
        == SyncDecisionStatus.REVIEW
    )
    assert (
        result.reason
        == SyncDecisionReason.STOCK_AND_COST_CHANGE_REQUIRES_REVIEW
    )


def test_missing_supplier_product_is_blocked():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(
                status=(
                    ComparisonStatus.MISSING_SUPPLIER_PRODUCT
                ),
                supplier_stock=None,
                stock_difference=None,
                supplier_cost=None,
                cost_difference=None,
            ),
            policy=InventorySyncPolicy(),
        )
    )

    assert (
        result.status
        == SyncDecisionStatus.BLOCKED
    )
    assert (
        result.reason
        == SyncDecisionReason.SUPPLIER_PRODUCT_MISSING
    )
    assert result.is_blocked is True


def test_missing_shopify_variant_is_blocked():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(
                status=(
                    ComparisonStatus.MISSING_SHOPIFY_VARIANT
                ),
                shopify_stock=None,
                stock_difference=None,
                cost_difference=None,
            ),
            policy=InventorySyncPolicy(),
        )
    )

    assert (
        result.status
        == SyncDecisionStatus.BLOCKED
    )
    assert (
        result.reason
        == SyncDecisionReason.SHOPIFY_VARIANT_MISSING
    )


def test_decision_preserves_identity():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(),
            policy=InventorySyncPolicy(),
        )
    )

    assert (
        result.supplier_code
        == "demo_supplier"
    )
    assert (
        result.supplier_sku
        == "SUP-CAP-001"
    )
    assert (
        result.shopify_sku
        == "AUTO-Cap-001"
    )


def test_eligible_decision_preserves_current_inventory():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(
                status=(
                    ComparisonStatus.STOCK_MISMATCH
                ),
                supplier_stock=40,
                shopify_stock=2,
                stock_difference=38,
            ),
            policy=InventorySyncPolicy(),
        )
    )

    assert (
        result.current_inventory_quantity
        == 2
    )
    assert (
        result.supplier_inventory_quantity
        == 40
    )
    assert (
        result.inventory_delta
        == 38
    )


def test_eligible_property_false_for_review():
    result = (
        evaluate_supplier_sync_decision(
            comparison=comparison(
                status=(
                    ComparisonStatus.COST_MISMATCH
                ),
                cost_difference=(
                    Decimal("1.00")
                ),
            ),
            policy=InventorySyncPolicy(),
        )
    )

    assert result.is_eligible is False
    assert (
        result.requires_human_review
        is True
    )
