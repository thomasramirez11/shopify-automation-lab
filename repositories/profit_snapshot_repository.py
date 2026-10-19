import logging

from database.connection import get_db_connection


logger = logging.getLogger(__name__)


class ProfitSnapshotRepository:
    """
    Handles immutable historical profit snapshots
    for Shopify order line items.
    """

    VALID_COST_SOURCES = {
        "manual",
        "supplier",
    }

    REQUIRED_CALCULATION_FIELDS = {
        "currency_code",
        "quantity",
        "unit_sale_price",
        "unit_cost",
        "line_revenue",
        "line_cost",
        "estimated_gross_profit",
        "gross_margin_percent",
    }

    def save_snapshot(
        self,
        *,
        shopify_line_item_id: str,
        shopify_order_id: str,
        shopify_variant_id: str | None,
        sku: str | None,
        calculation: dict,
        cost_source: str,
    ) -> bool:
        """
        Store one historical line-item profit snapshot.

        Returns:
            True if a new snapshot was created.
            False if this line item already has a snapshot.

        Existing snapshots are intentionally NOT updated.
        """

        self._validate_identifiers(
            shopify_line_item_id=shopify_line_item_id,
            shopify_order_id=shopify_order_id,
        )

        self._validate_calculation(
            calculation
        )

        normalized_source = (
            cost_source.strip().lower()
        )

        if normalized_source not in (
            self.VALID_COST_SOURCES
        ):
            raise ValueError(
                "cost_source must be "
                "'manual' or 'supplier'."
            )

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO order_line_item_profit_snapshots (
                    shopify_line_item_id,
                    shopify_order_id,
                    shopify_variant_id,
                    sku,
                    quantity,
                    currency_code,
                    unit_sale_price,
                    unit_cost,
                    line_revenue,
                    line_cost,
                    estimated_gross_profit,
                    gross_margin_percent,
                    cost_source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

                ON CONFLICT(shopify_line_item_id)
                DO NOTHING;
                """,
                (
                    shopify_line_item_id,
                    shopify_order_id,
                    shopify_variant_id,
                    sku,
                    calculation["quantity"],
                    calculation["currency_code"],
                    calculation["unit_sale_price"],
                    calculation["unit_cost"],
                    calculation["line_revenue"],
                    calculation["line_cost"],
                    calculation[
                        "estimated_gross_profit"
                    ],
                    calculation[
                        "gross_margin_percent"
                    ],
                    normalized_source,
                ),
            )

            snapshot_created = (
                cursor.rowcount == 1
            )

        if snapshot_created:
            logger.info(
                "Created profit snapshot for "
                "line item '%s'.",
                shopify_line_item_id,
            )
        else:
            logger.info(
                "Profit snapshot already exists "
                "for line item '%s'.",
                shopify_line_item_id,
            )

        return snapshot_created

    def get_snapshot_by_line_item_id(
        self,
        shopify_line_item_id: str,
    ):
        """
        Return one historical profit snapshot.

        Returns None if no snapshot exists.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    shopify_line_item_id,
                    shopify_order_id,
                    shopify_variant_id,
                    sku,
                    quantity,
                    currency_code,
                    unit_sale_price,
                    unit_cost,
                    line_revenue,
                    line_cost,
                    estimated_gross_profit,
                    gross_margin_percent,
                    cost_source,
                    calculated_at
                FROM order_line_item_profit_snapshots
                WHERE shopify_line_item_id = ?;
                """,
                (shopify_line_item_id,),
            )

            row = cursor.fetchone()

            if row is None:
                return None

            return dict(row)

    def get_snapshots_for_order(
        self,
        shopify_order_id: str,
    ) -> list:
        """
        Return all profit snapshots belonging
        to one Shopify order.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    shopify_line_item_id,
                    shopify_order_id,
                    shopify_variant_id,
                    sku,
                    quantity,
                    currency_code,
                    unit_sale_price,
                    unit_cost,
                    line_revenue,
                    line_cost,
                    estimated_gross_profit,
                    gross_margin_percent,
                    cost_source,
                    calculated_at
                FROM order_line_item_profit_snapshots
                WHERE shopify_order_id = ?
                ORDER BY id;
                """,
                (shopify_order_id,),
            )

            return [
                dict(row)
                for row in cursor.fetchall()
            ]

    def count_snapshots(self) -> int:
        """
        Return the number of historical
        profit snapshots.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM order_line_item_profit_snapshots;
                """
            )

            row = cursor.fetchone()

            return row["count"]

    def _validate_identifiers(
        self,
        *,
        shopify_line_item_id: str,
        shopify_order_id: str,
    ) -> None:
        """
        Validate required Shopify identifiers.
        """

        if not shopify_line_item_id:
            raise ValueError(
                "shopify_line_item_id is required."
            )

        if not shopify_order_id:
            raise ValueError(
                "shopify_order_id is required."
            )

    def _validate_calculation(
        self,
        calculation: dict,
    ) -> None:
        """
        Verify that ProfitService returned
        all fields required for persistence.
        """

        if not isinstance(
            calculation,
            dict,
        ):
            raise ValueError(
                "calculation must be a dictionary."
            )

        missing_fields = (
            self.REQUIRED_CALCULATION_FIELDS
            - calculation.keys()
        )

        if missing_fields:
            missing_text = ", ".join(
                sorted(missing_fields)
            )

            raise ValueError(
                "Profit calculation is missing "
                f"required fields: {missing_text}"
            )