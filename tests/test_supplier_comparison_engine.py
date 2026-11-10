from decimal import Decimal

import pytest

from supplier.comparison.engine import (
    compare_supplier_to_shopify,
)
from supplier.comparison.models import (
    ComparisonStatus,
    ShopifyVariantState,
    SupplierComparisonError,
)
from supplier.mapping.models import (
    SupplierVariantMapping,
)
from supplier.models import (
    SupplierProduct,
)


VARIANT_ID = (
    "gid://shopify/ProductVariant/56166258147700"
)


def make_mapping(
    *,
    supplier_sku="SUP-CAP-001",
    shopify_variant_id=VARIANT_ID,
    shopify_sku="AUTO-Cap-001",
):
    return SupplierVariantMapping(
        supplier_code="demo_supplier",
        supplier_sku=supplier_sku,
        shopify_variant_id=(
            shopify_variant_id
        ),
        shopify_sku=shopify_sku,
    )


def make_supplier_product(
    *,
    supplier_sku="SUP-CAP-001",
    stock_quantity=25,
    unit_cost="4.25",
):
    return SupplierProduct(
        supplier_sku=supplier_sku,
        title="Automation Test Cap",
        stock_quantity=stock_quantity,
        unit_cost=unit_cost,
        currency="USD",
    )


def make_shopify_state(
    *,
    shopify_variant_id=VARIANT_ID,
    shopify_sku="AUTO-Cap-001",
    inventory_quantity=25,
):
    return ShopifyVariantState(
        shopify_variant_id=(
            shopify_variant_id
        ),
        shopify_sku=shopify_sku,
        inventory_quantity=(
            inventory_quantity
        ),
    )


def test_exact_match():
    result = compare_supplier_to_shopify(
        mapping=make_mapping(),
        supplier_product=(
            make_supplier_product()
        ),
        shopify_variant=(
            make_shopify_state()
        ),
        stored_cost="4.25",
    )

    assert (
        result.status
        == ComparisonStatus.MATCH
    )
    assert (
        result.stock_difference
        == 0
    )
    assert (
        result.cost_difference
        == Decimal("0.00")
    )
    assert result.is_actionable is False


def test_stock_mismatch_only():
    result = compare_supplier_to_shopify(
        mapping=make_mapping(),
        supplier_product=(
            make_supplier_product(
                stock_quantity=25
            )
        ),
        shopify_variant=(
            make_shopify_state(
                inventory_quantity=1
            )
        ),
        stored_cost="4.25",
    )

    assert (
        result.status
        == ComparisonStatus.STOCK_MISMATCH
    )
    assert (
        result.stock_difference
        == 24
    )
    assert (
        result.has_stock_mismatch
        is True
    )
    assert (
        result.has_cost_mismatch
        is False
    )


def test_negative_stock_difference_is_supported():
    result = compare_supplier_to_shopify(
        mapping=make_mapping(),
        supplier_product=(
            make_supplier_product(
                stock_quantity=2
            )
        ),
        shopify_variant=(
            make_shopify_state(
                inventory_quantity=10
            )
        ),
        stored_cost="4.25",
    )

    assert (
        result.stock_difference
        == -8
    )
    assert (
        result.status
        == ComparisonStatus.STOCK_MISMATCH
    )


def test_cost_mismatch_only():
    result = compare_supplier_to_shopify(
        mapping=make_mapping(),
        supplier_product=(
            make_supplier_product(
                unit_cost="5.00"
            )
        ),
        shopify_variant=(
            make_shopify_state()
        ),
        stored_cost="4.25",
    )

    assert (
        result.status
        == ComparisonStatus.COST_MISMATCH
    )
    assert (
        result.cost_difference
        == Decimal("0.75")
    )
    assert (
        result.has_cost_mismatch
        is True
    )


def test_negative_cost_difference_is_supported():
    result = compare_supplier_to_shopify(
        mapping=make_mapping(),
        supplier_product=(
            make_supplier_product(
                unit_cost="3.75"
            )
        ),
        shopify_variant=(
            make_shopify_state()
        ),
        stored_cost="4.25",
    )

    assert (
        result.cost_difference
        == Decimal("-0.50")
    )
    assert (
        result.status
        == ComparisonStatus.COST_MISMATCH
    )


def test_stock_and_cost_mismatch():
    result = compare_supplier_to_shopify(
        mapping=make_mapping(),
        supplier_product=(
            make_supplier_product(
                stock_quantity=25,
                unit_cost="5.00",
            )
        ),
        shopify_variant=(
            make_shopify_state(
                inventory_quantity=1
            )
        ),
        stored_cost="4.25",
    )

    assert (
        result.status
        == ComparisonStatus.STOCK_AND_COST_MISMATCH
    )
    assert (
        result.stock_difference
        == 24
    )
    assert (
        result.cost_difference
        == Decimal("0.75")
    )


def test_missing_stored_cost_does_not_create_fake_cost_mismatch():
    result = compare_supplier_to_shopify(
        mapping=make_mapping(),
        supplier_product=(
            make_supplier_product()
        ),
        shopify_variant=(
            make_shopify_state()
        ),
        stored_cost=None,
    )

    assert (
        result.status
        == ComparisonStatus.MATCH
    )
    assert (
        result.cost_difference
        is None
    )
    assert (
        result.stored_cost
        is None
    )


def test_missing_supplier_product():
    result = compare_supplier_to_shopify(
        mapping=make_mapping(),
        supplier_product=None,
        shopify_variant=(
            make_shopify_state()
        ),
        stored_cost="4.25",
    )

    assert (
        result.status
        == ComparisonStatus.MISSING_SUPPLIER_PRODUCT
    )
    assert (
        result.supplier_stock
        is None
    )
    assert result.is_actionable is True


def test_missing_shopify_variant():
    result = compare_supplier_to_shopify(
        mapping=make_mapping(),
        supplier_product=(
            make_supplier_product()
        ),
        shopify_variant=None,
        stored_cost="4.25",
    )

    assert (
        result.status
        == ComparisonStatus.MISSING_SHOPIFY_VARIANT
    )
    assert (
        result.shopify_stock
        is None
    )


def test_supplier_sku_must_match_mapping():
    with pytest.raises(
        SupplierComparisonError,
        match="supplier_product SKU does not match",
    ):
        compare_supplier_to_shopify(
            mapping=make_mapping(),
            supplier_product=(
                make_supplier_product(
                    supplier_sku="SUP-WRONG"
                )
            ),
            shopify_variant=(
                make_shopify_state()
            ),
            stored_cost="4.25",
        )


def test_shopify_variant_id_must_match_mapping():
    with pytest.raises(
        SupplierComparisonError,
        match="shopify_variant ID does not match",
    ):
        compare_supplier_to_shopify(
            mapping=make_mapping(),
            supplier_product=(
                make_supplier_product()
            ),
            shopify_variant=(
                make_shopify_state(
                    shopify_variant_id=(
                        "gid://shopify/ProductVariant/999999"
                    )
                )
            ),
            stored_cost="4.25",
        )


def test_shopify_sku_must_match_mapping():
    with pytest.raises(
        SupplierComparisonError,
        match="shopify_variant SKU does not match",
    ):
        compare_supplier_to_shopify(
            mapping=make_mapping(),
            supplier_product=(
                make_supplier_product()
            ),
            shopify_variant=(
                make_shopify_state(
                    shopify_sku="WRONG-SKU"
                )
            ),
            stored_cost="4.25",
        )


def test_invalid_stored_cost_is_rejected():
    with pytest.raises(
        SupplierComparisonError,
        match="stored_cost must be a valid decimal",
    ):
        compare_supplier_to_shopify(
            mapping=make_mapping(),
            supplier_product=(
                make_supplier_product()
            ),
            shopify_variant=(
                make_shopify_state()
            ),
            stored_cost="bad-money",
        )


def test_negative_stored_cost_is_rejected():
    with pytest.raises(
        SupplierComparisonError,
        match="stored_cost cannot be negative",
    ):
        compare_supplier_to_shopify(
            mapping=make_mapping(),
            supplier_product=(
                make_supplier_product()
            ),
            shopify_variant=(
                make_shopify_state()
            ),
            stored_cost="-1.00",
        )


def test_shopify_state_rejects_negative_inventory():
    with pytest.raises(
        SupplierComparisonError,
        match="inventory_quantity cannot be negative",
    ):
        make_shopify_state(
            inventory_quantity=-1
        )


def test_shopify_state_rejects_non_integer_inventory():
    with pytest.raises(
        SupplierComparisonError,
        match="inventory_quantity must be an integer",
    ):
        make_shopify_state(
            inventory_quantity=2.5
        )


def test_shopify_state_rejects_empty_sku():
    with pytest.raises(
        SupplierComparisonError,
        match="shopify_sku cannot be empty",
    ):
        make_shopify_state(
            shopify_sku="   "
        )


def test_shopify_state_rejects_non_variant_gid():
    with pytest.raises(
        SupplierComparisonError,
        match="Shopify ProductVariant GID",
    ):
        make_shopify_state(
            shopify_variant_id=(
                "gid://shopify/Product/123"
            )
        )


def test_result_preserves_normalized_identity():
    result = compare_supplier_to_shopify(
        mapping=make_mapping(),
        supplier_product=(
            make_supplier_product()
        ),
        shopify_variant=(
            make_shopify_state()
        ),
        stored_cost="4.25",
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
