from __future__ import annotations

from collections.abc import Iterable

from supplier.mapping.models import (
    SupplierMappingError,
    SupplierVariantMapping,
)


class InMemorySupplierMappingRegistry:
    """
    Read-only in-memory mapping registry for V2 development.

    Safety rule:
    - one supplier SKU may map to only one Shopify variant
    - one Shopify variant may be controlled by only one supplier mapping

    Multi-source supplier selection can be added later through an explicit
    sourcing policy rather than allowing silent conflicts here.
    """

    def __init__(
        self,
        mappings: Iterable[
            SupplierVariantMapping
        ],
    ) -> None:
        self._by_supplier: dict[
            tuple[str, str],
            SupplierVariantMapping,
        ] = {}

        self._by_shopify_variant_id: dict[
            str,
            SupplierVariantMapping,
        ] = {}

        self._ordered: list[
            SupplierVariantMapping
        ] = []

        for mapping in mappings:
            supplier_key = (
                mapping.supplier_key
            )

            if (
                supplier_key
                in self._by_supplier
            ):
                raise SupplierMappingError(
                    "Duplicate supplier mapping for "
                    f"{supplier_key[0]} / "
                    f"{supplier_key[1]}."
                )

            if (
                mapping.shopify_variant_id
                in self._by_shopify_variant_id
            ):
                existing = (
                    self._by_shopify_variant_id[
                        mapping.shopify_variant_id
                    ]
                )

                raise SupplierMappingError(
                    "Shopify variant is already mapped: "
                    f"{mapping.shopify_variant_id} "
                    f"({existing.supplier_code} / "
                    f"{existing.supplier_sku})."
                )

            self._by_supplier[
                supplier_key
            ] = mapping

            self._by_shopify_variant_id[
                mapping.shopify_variant_id
            ] = mapping

            self._ordered.append(
                mapping
            )

    def list_mappings(
        self,
        *,
        active_only: bool = False,
    ) -> tuple[
        SupplierVariantMapping,
        ...,
    ]:
        """
        Return an immutable mapping snapshot.
        """

        if not active_only:
            return tuple(
                self._ordered
            )

        return tuple(
            mapping
            for mapping in self._ordered
            if mapping.active
        )

    def get_by_supplier(
        self,
        supplier_code: str,
        supplier_sku: str,
    ) -> SupplierVariantMapping | None:
        """
        Resolve a normalized supplier identity.
        """

        key = (
            supplier_code
            .strip()
            .lower(),
            supplier_sku.strip(),
        )

        return self._by_supplier.get(
            key
        )

    def get_by_shopify_variant_id(
        self,
        shopify_variant_id: str,
    ) -> SupplierVariantMapping | None:
        """
        Resolve one Shopify variant GID.
        """

        normalized_variant_id = (
            shopify_variant_id.strip()
        )

        return (
            self._by_shopify_variant_id
            .get(
                normalized_variant_id
            )
        )
