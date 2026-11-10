from __future__ import annotations

from typing import Protocol

from supplier.models import SupplierProduct


class SupplierCatalogPort(Protocol):
    """
    Interface the application uses to read supplier catalog data.

    Future adapters can satisfy this same contract whether their data
    comes from JSON, CSV, REST, GraphQL, FTP, or another source.
    """

    def list_products(
        self,
    ) -> tuple[SupplierProduct, ...]:
        """
        Return the supplier catalog in normalized form.
        """

    def get_product_by_sku(
        self,
        supplier_sku: str,
    ) -> SupplierProduct | None:
        """
        Return one supplier product by supplier SKU when available.
        """
