import logging
from decimal import Decimal, InvalidOperation

from database.connection import get_db_connection


logger = logging.getLogger(__name__)


class CostRepository:
    """
    Handles persistence and retrieval of current variant costs.
    """

    VALID_COST_SOURCES = {
        "manual",
        "supplier",
    }

    def set_variant_cost(
        self,
        shopify_variant_id: str,
        sku: str | None,
        unit_cost,
        currency_code: str,
        cost_source: str = "manual",
    ) -> None:
        """
        Insert or update the current cost for one Shopify variant.
        """

        normalized_cost = self._normalize_cost(
            unit_cost
        )

        normalized_currency = (
            currency_code.strip().upper()
        )

        normalized_source = (
            cost_source.strip().lower()
        )

        if not shopify_variant_id:
            raise ValueError(
                "shopify_variant_id is required."
            )

        if not normalized_currency:
            raise ValueError(
                "currency_code is required."
            )

        if normalized_source not in (
            self.VALID_COST_SOURCES
        ):
            raise ValueError(
                "cost_source must be "
                "'manual' or 'supplier'."
            )

        with get_db_connection() as connection:
            connection.execute(
                """
                INSERT INTO variant_costs (
                    shopify_variant_id,
                    sku,
                    unit_cost,
                    currency_code,
                    cost_source
                )
                VALUES (?, ?, ?, ?, ?)

                ON CONFLICT(shopify_variant_id)
                DO UPDATE SET
                    sku = excluded.sku,
                    unit_cost = excluded.unit_cost,
                    currency_code = excluded.currency_code,
                    cost_source = excluded.cost_source,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (
                    shopify_variant_id,
                    sku,
                    normalized_cost,
                    normalized_currency,
                    normalized_source,
                ),
            )

        logger.info(
            "Saved cost for variant '%s'.",
            shopify_variant_id,
        )

    def get_cost_by_variant_id(
        self,
        shopify_variant_id: str,
    ):
        """
        Return the current cost configuration
        for one Shopify variant.

        Returns None if no cost exists.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    shopify_variant_id,
                    sku,
                    unit_cost,
                    currency_code,
                    cost_source,
                    updated_at
                FROM variant_costs
                WHERE shopify_variant_id = ?;
                """,
                (shopify_variant_id,),
            )

            row = cursor.fetchone()

            if row is None:
                return None

            return dict(row)

    def get_cost_by_sku(
        self,
        sku: str,
    ):
        """
        Return the current cost configuration
        for one SKU.

        Returns None if no cost exists.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    shopify_variant_id,
                    sku,
                    unit_cost,
                    currency_code,
                    cost_source,
                    updated_at
                FROM variant_costs
                WHERE sku = ?
                ORDER BY updated_at DESC
                LIMIT 1;
                """,
                (sku,),
            )

            row = cursor.fetchone()

            if row is None:
                return None

            return dict(row)

    def get_all_costs(self) -> list:
        """
        Return all current variant cost configurations.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    shopify_variant_id,
                    sku,
                    unit_cost,
                    currency_code,
                    cost_source,
                    updated_at
                FROM variant_costs
                ORDER BY sku,
                         shopify_variant_id;
                """
            )

            return [
                dict(row)
                for row in cursor.fetchall()
            ]

    def count_costs(self) -> int:
        """
        Return the number of configured variant costs.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM variant_costs;
                """
            )

            row = cursor.fetchone()

            return row["count"]

    def _normalize_cost(
        self,
        unit_cost,
    ) -> str:
        """
        Validate a monetary cost and return
        a normalized decimal string.
        """

        try:
            decimal_cost = Decimal(
                str(unit_cost)
            )
        except (
            InvalidOperation,
            ValueError,
            TypeError,
        ) as exc:
            raise ValueError(
                "unit_cost must be a valid "
                "decimal number."
            ) from exc

        if decimal_cost < 0:
            raise ValueError(
                "unit_cost cannot be negative."
            )

        return format(
            decimal_cost,
            "f",
        )