from __future__ import annotations

from collections.abc import Iterable

from supplier.models import (
    SupplierDataError,
    SupplierProduct,
)


class FakeSupplierAdapter:
    """
    In-memory supplier adapter used for V2 development and tests.

    It deliberately does not call Shopify and does not modify any data
    outside its own in-memory catalog.
    """

    def __init__(
        self,
        products: Iterable[SupplierProduct],
    ) -> None:
        self._products_by_sku: dict[
            str,
            SupplierProduct,
        ] = {}

        for product in products:
            key = product.supplier_sku

            if key in self._products_by_sku:
                raise SupplierDataError(
                    "Duplicate supplier SKU: "
                    f"{key}"
                )

            self._products_by_sku[key] = product

    def list_products(
        self,
    ) -> tuple[SupplierProduct, ...]:
        """
        Return an immutable snapshot of the current fake catalog.
        """

        return tuple(
            self._products_by_sku.values()
        )

    def get_product_by_sku(
        self,
        supplier_sku: str,
    ) -> SupplierProduct | None:
        """
        Lookup is tolerant of accidental surrounding whitespace.
        """

        normalized_sku = (
            supplier_sku.strip()
        )

        return self._products_by_sku.get(
            normalized_sku
        )
