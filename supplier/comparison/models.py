from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum


class SupplierComparisonError(ValueError):
    """
    Raised when comparison input data is invalid.
    """


class ComparisonStatus(str, Enum):
    """
    Deterministic result categories for supplier-vs-Shopify comparison.
    """

    MATCH = "match"
    STOCK_MISMATCH = "stock_mismatch"
    COST_MISMATCH = "cost_mismatch"
    STOCK_AND_COST_MISMATCH = "stock_and_cost_mismatch"
    MISSING_SUPPLIER_PRODUCT = "missing_supplier_product"
    MISSING_SHOPIFY_VARIANT = "missing_shopify_variant"


@dataclass(frozen=True)
class ShopifyVariantState:
    """
    Read-only normalized Shopify-side state used by the comparison engine.

    This object does not perform Shopify API calls.
    """

    shopify_variant_id: str
    shopify_sku: str
    inventory_quantity: int

    def __post_init__(self) -> None:
        variant_id = (
            self.shopify_variant_id
            .strip()
        )

        sku = self.shopify_sku.strip()

        if not variant_id.startswith(
            "gid://shopify/ProductVariant/"
        ):
            raise SupplierComparisonError(
                "shopify_variant_id must be a Shopify ProductVariant GID."
            )

        if not sku:
            raise SupplierComparisonError(
                "shopify_sku cannot be empty."
            )

        if isinstance(
            self.inventory_quantity,
            bool,
        ) or not isinstance(
            self.inventory_quantity,
            int,
        ):
            raise SupplierComparisonError(
                "inventory_quantity must be an integer."
            )

        if self.inventory_quantity < 0:
            raise SupplierComparisonError(
                "inventory_quantity cannot be negative."
            )

        object.__setattr__(
            self,
            "shopify_variant_id",
            variant_id,
        )

        object.__setattr__(
            self,
            "shopify_sku",
            sku,
        )


@dataclass(frozen=True)
class SupplierShopifyComparison:
    """
    Immutable comparison result.

    Positive stock_difference means the supplier reports more stock than
    Shopify. Positive cost_difference means supplier cost is higher than
    the stored Shopify Automation Lab cost.
    """

    supplier_code: str
    supplier_sku: str
    shopify_variant_id: str
    shopify_sku: str
    status: ComparisonStatus

    supplier_stock: int | None
    shopify_stock: int | None
    stock_difference: int | None

    supplier_cost: Decimal | None
    stored_cost: Decimal | None
    cost_difference: Decimal | None

    @property
    def has_stock_mismatch(
        self,
    ) -> bool:
        return self.status in {
            ComparisonStatus.STOCK_MISMATCH,
            ComparisonStatus.STOCK_AND_COST_MISMATCH,
        }

    @property
    def has_cost_mismatch(
        self,
    ) -> bool:
        return self.status in {
            ComparisonStatus.COST_MISMATCH,
            ComparisonStatus.STOCK_AND_COST_MISMATCH,
        }

    @property
    def is_actionable(
        self,
    ) -> bool:
        """
        Missing data or any mismatch deserves downstream attention.
        """

        return (
            self.status
            != ComparisonStatus.MATCH
        )


def normalize_optional_cost(
    value,
) -> Decimal | None:
    """
    Normalize one optional monetary value.
    """

    if value is None:
        return None

    try:
        parsed = Decimal(
            str(value)
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ) as exc:
        raise SupplierComparisonError(
            "stored_cost must be a valid decimal number."
        ) from exc

    if parsed < 0:
        raise SupplierComparisonError(
            "stored_cost cannot be negative."
        )

    return parsed
