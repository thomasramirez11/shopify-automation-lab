from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable

from database.connection import get_db_connection
from supplier.comparison.models import (
    ShopifyVariantState,
    SupplierComparisonError,
)


class ShopifySnapshotError(ValueError):
    """
    Raised when persisted Shopify state cannot be normalized safely.
    """


@dataclass(frozen=True)
class ShopifyComparisonSnapshot:
    """
    Read-only V1 SQLite snapshot used by the V2 comparison engine.
    """

    shopify_variant: ShopifyVariantState
    stored_cost: Decimal | None
    cost_currency: str | None
    cost_source: str | None


class SQLiteShopifyComparisonSnapshotAdapter:
    """
    Read normalized Shopify comparison state from the existing V1 database.

    This adapter is deliberately read-only:
    - no Shopify API calls
    - no SQLite INSERT/UPDATE/DELETE
    - no supplier writes
    """

    def __init__(
        self,
        *,
        connection_factory: Callable = get_db_connection,
    ) -> None:
        self._connection_factory = (
            connection_factory
        )

    def get_snapshot(
        self,
        shopify_variant_id: str,
    ) -> ShopifyComparisonSnapshot | None:
        """
        Return one persisted Shopify variant snapshot.

        None means the mapped Shopify variant is absent from V1 SQLite.
        """

        normalized_variant_id = (
            shopify_variant_id.strip()
        )

        if not normalized_variant_id:
            raise ShopifySnapshotError(
                "shopify_variant_id cannot be empty."
            )

        with self._connection_factory() as connection:
            cursor = connection.execute(
                """
                SELECT
                    v.shopify_variant_id,
                    v.sku,
                    v.inventory_quantity,
                    vc.unit_cost,
                    vc.currency_code,
                    vc.cost_source
                FROM variants AS v

                LEFT JOIN variant_costs AS vc
                    ON vc.shopify_variant_id =
                       v.shopify_variant_id

                WHERE v.shopify_variant_id = ?;
                """,
                (
                    normalized_variant_id,
                ),
            )

            row = cursor.fetchone()

        if row is None:
            return None

        row_data = dict(row)

        sku = row_data.get(
            "sku"
        )

        if not isinstance(
            sku,
            str,
        ) or not sku.strip():
            raise ShopifySnapshotError(
                "Persisted mapped Shopify variant must have a non-empty SKU."
            )

        inventory_quantity = (
            row_data.get(
                "inventory_quantity"
            )
        )

        if inventory_quantity is None:
            raise ShopifySnapshotError(
                "Persisted mapped Shopify variant must have inventory_quantity."
            )

        try:
            shopify_variant = (
                ShopifyVariantState(
                    shopify_variant_id=(
                        row_data[
                            "shopify_variant_id"
                        ]
                    ),
                    shopify_sku=sku,
                    inventory_quantity=(
                        inventory_quantity
                    ),
                )
            )

        except SupplierComparisonError as exc:
            raise ShopifySnapshotError(
                "Persisted Shopify variant state is invalid: "
                f"{exc}"
            ) from exc

        stored_cost = (
            self._normalize_optional_cost(
                row_data.get(
                    "unit_cost"
                )
            )
        )

        cost_currency = (
            self._normalize_optional_text(
                row_data.get(
                    "currency_code"
                )
            )
        )

        cost_source = (
            self._normalize_optional_text(
                row_data.get(
                    "cost_source"
                )
            )
        )

        if stored_cost is None:
            cost_currency = None
            cost_source = None

        return ShopifyComparisonSnapshot(
            shopify_variant=(
                shopify_variant
            ),
            stored_cost=stored_cost,
            cost_currency=(
                cost_currency
            ),
            cost_source=cost_source,
        )

    def _normalize_optional_cost(
        self,
        value,
    ) -> Decimal | None:
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
            raise ShopifySnapshotError(
                "Persisted unit_cost must be a valid decimal number."
            ) from exc

        if parsed < 0:
            raise ShopifySnapshotError(
                "Persisted unit_cost cannot be negative."
            )

        return parsed

    def _normalize_optional_text(
        self,
        value,
    ) -> str | None:
        if value is None:
            return None

        normalized = str(
            value
        ).strip()

        return (
            normalized
            if normalized
            else None
        )
