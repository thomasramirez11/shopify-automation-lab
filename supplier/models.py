from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation


class SupplierDataError(ValueError):
    """
    Raised when supplier data violates the V2 supplier contract.
    """


@dataclass(frozen=True)
class SupplierProduct:
    """
    Normalized supplier-side product data.

    Shopify-specific IDs do not belong here. This object represents what
    the supplier says about one supplier product/SKU.
    """

    supplier_sku: str
    title: str
    stock_quantity: int
    unit_cost: Decimal
    currency: str
    source_updated_at: datetime | None = None

    def __post_init__(self) -> None:
        normalized_sku = self.supplier_sku.strip()
        normalized_title = self.title.strip()
        normalized_currency = self.currency.strip().upper()

        if not normalized_sku:
            raise SupplierDataError(
                "supplier_sku cannot be empty."
            )

        if not normalized_title:
            raise SupplierDataError(
                "title cannot be empty."
            )

        if isinstance(self.stock_quantity, bool) or not isinstance(
            self.stock_quantity,
            int,
        ):
            raise SupplierDataError(
                "stock_quantity must be an integer."
            )

        if self.stock_quantity < 0:
            raise SupplierDataError(
                "stock_quantity cannot be negative."
            )

        try:
            normalized_cost = Decimal(
                str(self.unit_cost)
            )

        except (
            InvalidOperation,
            ValueError,
            TypeError,
        ) as exc:
            raise SupplierDataError(
                "unit_cost must be a valid decimal number."
            ) from exc

        if normalized_cost < 0:
            raise SupplierDataError(
                "unit_cost cannot be negative."
            )

        if (
            len(normalized_currency) != 3
            or not normalized_currency.isalpha()
        ):
            raise SupplierDataError(
                "currency must be a 3-letter code."
            )

        if (
            self.source_updated_at is not None
            and (
                self.source_updated_at.tzinfo is None
                or self.source_updated_at.utcoffset() is None
            )
        ):
            raise SupplierDataError(
                "source_updated_at must be timezone-aware."
            )

        object.__setattr__(
            self,
            "supplier_sku",
            normalized_sku,
        )

        object.__setattr__(
            self,
            "title",
            normalized_title,
        )

        object.__setattr__(
            self,
            "unit_cost",
            normalized_cost,
        )

        object.__setattr__(
            self,
            "currency",
            normalized_currency,
        )
