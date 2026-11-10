from __future__ import annotations

from supplier.comparison.models import (
    ComparisonStatus,
    ShopifyVariantState,
    SupplierComparisonError,
    SupplierShopifyComparison,
    normalize_optional_cost,
)
from supplier.mapping.models import (
    SupplierVariantMapping,
)
from supplier.models import (
    SupplierProduct,
)


def compare_supplier_to_shopify(
    *,
    mapping: SupplierVariantMapping,
    supplier_product: SupplierProduct | None,
    shopify_variant: ShopifyVariantState | None,
    stored_cost=None,
) -> SupplierShopifyComparison:
    """
    Compare one explicit mapping against normalized supplier and Shopify data.

    This function is pure:
    - no database writes
    - no Shopify writes
    - no network calls
    - no alerts

    It only returns a deterministic comparison result.
    """

    normalized_stored_cost = (
        normalize_optional_cost(
            stored_cost
        )
    )

    if supplier_product is None:
        return SupplierShopifyComparison(
            supplier_code=(
                mapping.supplier_code
            ),
            supplier_sku=(
                mapping.supplier_sku
            ),
            shopify_variant_id=(
                mapping.shopify_variant_id
            ),
            shopify_sku=(
                mapping.shopify_sku
            ),
            status=(
                ComparisonStatus
                .MISSING_SUPPLIER_PRODUCT
            ),
            supplier_stock=None,
            shopify_stock=(
                shopify_variant.inventory_quantity
                if shopify_variant
                is not None
                else None
            ),
            stock_difference=None,
            supplier_cost=None,
            stored_cost=(
                normalized_stored_cost
            ),
            cost_difference=None,
        )

    if (
        supplier_product.supplier_sku
        != mapping.supplier_sku
    ):
        raise SupplierComparisonError(
            "supplier_product SKU does not match the mapping."
        )

    if shopify_variant is None:
        return SupplierShopifyComparison(
            supplier_code=(
                mapping.supplier_code
            ),
            supplier_sku=(
                mapping.supplier_sku
            ),
            shopify_variant_id=(
                mapping.shopify_variant_id
            ),
            shopify_sku=(
                mapping.shopify_sku
            ),
            status=(
                ComparisonStatus
                .MISSING_SHOPIFY_VARIANT
            ),
            supplier_stock=(
                supplier_product.stock_quantity
            ),
            shopify_stock=None,
            stock_difference=None,
            supplier_cost=(
                supplier_product.unit_cost
            ),
            stored_cost=(
                normalized_stored_cost
            ),
            cost_difference=None,
        )

    if (
        shopify_variant.shopify_variant_id
        != mapping.shopify_variant_id
    ):
        raise SupplierComparisonError(
            "shopify_variant ID does not match the mapping."
        )

    if (
        shopify_variant.shopify_sku
        != mapping.shopify_sku
    ):
        raise SupplierComparisonError(
            "shopify_variant SKU does not match the mapping."
        )

    stock_difference = (
        supplier_product.stock_quantity
        - shopify_variant.inventory_quantity
    )

    cost_difference = None

    if normalized_stored_cost is not None:
        cost_difference = (
            supplier_product.unit_cost
            - normalized_stored_cost
        )

    stock_mismatch = (
        stock_difference != 0
    )

    cost_mismatch = (
        cost_difference is not None
        and cost_difference != 0
    )

    if (
        stock_mismatch
        and cost_mismatch
    ):
        status = (
            ComparisonStatus
            .STOCK_AND_COST_MISMATCH
        )

    elif stock_mismatch:
        status = (
            ComparisonStatus
            .STOCK_MISMATCH
        )

    elif cost_mismatch:
        status = (
            ComparisonStatus
            .COST_MISMATCH
        )

    else:
        status = (
            ComparisonStatus.MATCH
        )

    return SupplierShopifyComparison(
        supplier_code=(
            mapping.supplier_code
        ),
        supplier_sku=(
            mapping.supplier_sku
        ),
        shopify_variant_id=(
            mapping.shopify_variant_id
        ),
        shopify_sku=(
            mapping.shopify_sku
        ),
        status=status,
        supplier_stock=(
            supplier_product.stock_quantity
        ),
        shopify_stock=(
            shopify_variant.inventory_quantity
        ),
        stock_difference=(
            stock_difference
        ),
        supplier_cost=(
            supplier_product.unit_cost
        ),
        stored_cost=(
            normalized_stored_cost
        ),
        cost_difference=(
            cost_difference
        ),
    )
