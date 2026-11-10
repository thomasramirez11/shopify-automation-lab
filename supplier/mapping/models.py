from __future__ import annotations

import re
from dataclasses import dataclass


SUPPLIER_CODE_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9_-]*$"
)

SHOPIFY_VARIANT_GID_PATTERN = re.compile(
    r"^gid://shopify/ProductVariant/\d+$"
)


class SupplierMappingError(ValueError):
    """
    Raised when a supplier-to-Shopify mapping is invalid or ambiguous.
    """


@dataclass(frozen=True)
class SupplierVariantMapping:
    """
    Explicit relationship between one supplier SKU and one Shopify variant.

    supplier_code is included from the beginning so future V2 versions can
    support multiple suppliers without changing the identity of a mapping.
    """

    supplier_code: str
    supplier_sku: str
    shopify_variant_id: str
    shopify_sku: str
    active: bool = True

    def __post_init__(self) -> None:
        normalized_supplier_code = (
            self.supplier_code
            .strip()
            .lower()
        )

        normalized_supplier_sku = (
            self.supplier_sku
            .strip()
        )

        normalized_variant_id = (
            self.shopify_variant_id
            .strip()
        )

        normalized_shopify_sku = (
            self.shopify_sku
            .strip()
        )

        if not normalized_supplier_code:
            raise SupplierMappingError(
                "supplier_code cannot be empty."
            )

        if not SUPPLIER_CODE_PATTERN.fullmatch(
            normalized_supplier_code
        ):
            raise SupplierMappingError(
                "supplier_code must contain only lowercase letters, "
                "numbers, underscores, or hyphens."
            )

        if not normalized_supplier_sku:
            raise SupplierMappingError(
                "supplier_sku cannot be empty."
            )

        if not SHOPIFY_VARIANT_GID_PATTERN.fullmatch(
            normalized_variant_id
        ):
            raise SupplierMappingError(
                "shopify_variant_id must be a Shopify ProductVariant GID."
            )

        if not normalized_shopify_sku:
            raise SupplierMappingError(
                "shopify_sku cannot be empty."
            )

        if not isinstance(
            self.active,
            bool,
        ):
            raise SupplierMappingError(
                "active must be a boolean."
            )

        object.__setattr__(
            self,
            "supplier_code",
            normalized_supplier_code,
        )

        object.__setattr__(
            self,
            "supplier_sku",
            normalized_supplier_sku,
        )

        object.__setattr__(
            self,
            "shopify_variant_id",
            normalized_variant_id,
        )

        object.__setattr__(
            self,
            "shopify_sku",
            normalized_shopify_sku,
        )

    @property
    def supplier_key(
        self,
    ) -> tuple[str, str]:
        """
        Stable identity for a supplier-side mapping.
        """

        return (
            self.supplier_code,
            self.supplier_sku,
        )
