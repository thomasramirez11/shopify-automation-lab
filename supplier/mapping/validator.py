from __future__ import annotations

from dataclasses import dataclass

from supplier.mapping.ports import (
    SupplierMappingPort,
)
from supplier.models import (
    SupplierProduct,
)
from supplier.ports import (
    SupplierCatalogPort,
)


@dataclass(frozen=True)
class SupplierMappingValidationReport:
    """
    Cross-validation result for one supplier feed and its explicit mappings.
    """

    supplier_code: str
    supplier_products_seen: int
    active_mappings_checked: int
    valid_mappings: int
    missing_supplier_skus: tuple[str, ...]
    unmapped_supplier_skus: tuple[str, ...]

    @property
    def passed(
        self,
    ) -> bool:
        """
        A missing mapped supplier SKU is unsafe and blocks comparison.
        """

        return not self.missing_supplier_skus


def validate_supplier_mapping_catalog(
    *,
    supplier_code: str,
    supplier_catalog: SupplierCatalogPort,
    mapping_registry: SupplierMappingPort,
) -> SupplierMappingValidationReport:
    """
    Prove that active mappings reference supplier SKUs present in the feed.

    Unmapped supplier products are allowed because a supplier catalog may
    contain products the Shopify store does not sell.
    """

    normalized_supplier_code = (
        supplier_code
        .strip()
        .lower()
    )

    products = (
        supplier_catalog.list_products()
    )

    products_by_sku: dict[
        str,
        SupplierProduct,
    ] = {
        product.supplier_sku: product
        for product in products
    }

    active_mappings = tuple(
        mapping
        for mapping in (
            mapping_registry.list_mappings(
                active_only=True
            )
        )
        if (
            mapping.supplier_code
            == normalized_supplier_code
        )
    )

    missing_supplier_skus = tuple(
        sorted(
            mapping.supplier_sku
            for mapping in active_mappings
            if (
                mapping.supplier_sku
                not in products_by_sku
            )
        )
    )

    valid_mappings = sum(
        1
        for mapping in active_mappings
        if (
            mapping.supplier_sku
            in products_by_sku
        )
    )

    mapped_supplier_skus = {
        mapping.supplier_sku
        for mapping in active_mappings
        if (
            mapping.supplier_sku
            in products_by_sku
        )
    }

    unmapped_supplier_skus = tuple(
        sorted(
            supplier_sku
            for supplier_sku
            in products_by_sku
            if supplier_sku
            not in mapped_supplier_skus
        )
    )

    return SupplierMappingValidationReport(
        supplier_code=(
            normalized_supplier_code
        ),
        supplier_products_seen=(
            len(products)
        ),
        active_mappings_checked=(
            len(active_mappings)
        ),
        valid_mappings=(
            valid_mappings
        ),
        missing_supplier_skus=(
            missing_supplier_skus
        ),
        unmapped_supplier_skus=(
            unmapped_supplier_skus
        ),
    )
