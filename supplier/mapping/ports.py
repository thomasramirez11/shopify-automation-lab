from __future__ import annotations

from typing import Protocol

from supplier.mapping.models import (
    SupplierVariantMapping,
)


class SupplierMappingPort(Protocol):
    """
    Application-facing contract for explicit supplier mappings.

    A later implementation may persist mappings in SQLite without changing
    code that depends on this interface.
    """

    def list_mappings(
        self,
        *,
        active_only: bool = False,
    ) -> tuple[SupplierVariantMapping, ...]:
        """
        Return known mappings.
        """

    def get_by_supplier(
        self,
        supplier_code: str,
        supplier_sku: str,
    ) -> SupplierVariantMapping | None:
        """
        Resolve one supplier identity to its Shopify variant mapping.
        """

    def get_by_shopify_variant_id(
        self,
        shopify_variant_id: str,
    ) -> SupplierVariantMapping | None:
        """
        Resolve one Shopify variant to its supplier mapping.
        """
