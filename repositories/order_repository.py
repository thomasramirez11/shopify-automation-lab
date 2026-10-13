import logging

from database.connection import get_db_connection


logger = logging.getLogger(__name__)


class OrderRepository:
    """
    Handles SQLite persistence for Shopify orders and line items.
    """

    def save_order(self, order: dict) -> bool:
        """
        Save one Shopify order and all of its line items.

        Existing orders are updated instead of duplicated.

        Line items are refreshed as one complete order snapshot.

        Returns:
            True if this is a newly discovered order.
            False if the order already existed.
        """

        with get_db_connection() as connection:
            is_new_order = not self._order_exists(
                connection=connection,
                order_id=order["id"],
            )

            self._upsert_order(
                connection=connection,
                order=order,
            )

            self._replace_line_items(
                connection=connection,
                order=order,
            )

        if is_new_order:
            logger.info(
                "New Shopify order detected: '%s'.",
                order["name"],
            )
        else:
            logger.info(
                "Updated existing Shopify order: '%s'.",
                order["name"],
            )

        return is_new_order

    def _order_exists(
        self,
        connection,
        order_id: str,
    ) -> bool:
        """
        Return True if the Shopify order already exists
        in SQLite.
        """

        cursor = connection.execute(
            """
            SELECT 1
            FROM orders
            WHERE shopify_order_id = ?
            LIMIT 1;
            """,
            (order_id,),
        )

        return cursor.fetchone() is not None

    def _upsert_order(
        self,
        connection,
        order: dict,
    ) -> None:
        """
        Insert a new order or update an existing order.
        """

        total_price_set = (
            order.get("totalPriceSet")
            or {}
        )

        shop_money = (
            total_price_set.get("shopMoney")
            or {}
        )

        total_price = shop_money.get("amount")

        currency_code = shop_money.get(
            "currencyCode"
        )

        if total_price is None:
            raise ValueError(
                f"Order {order.get('name')} "
                "has no total price."
            )

        if currency_code is None:
            raise ValueError(
                f"Order {order.get('name')} "
                "has no currency code."
            )

        connection.execute(
            """
            INSERT INTO orders (
                shopify_order_id,
                order_name,
                created_at,
                updated_at,
                currency_code,
                total_price,
                financial_status,
                fulfillment_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(shopify_order_id)
            DO UPDATE SET
                order_name = excluded.order_name,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                currency_code = excluded.currency_code,
                total_price = excluded.total_price,
                financial_status = excluded.financial_status,
                fulfillment_status = excluded.fulfillment_status,
                synced_at = CURRENT_TIMESTAMP;
            """,
            (
                order["id"],
                order["name"],
                order["createdAt"],
                order["updatedAt"],
                currency_code,
                total_price,
                order.get(
                    "displayFinancialStatus"
                ),
                order.get(
                    "displayFulfillmentStatus"
                ),
            ),
        )

    def _replace_line_items(
        self,
        connection,
        order: dict,
    ) -> None:
        """
        Replace all stored line items for one order
        with Shopify's current order snapshot.
        """

        order_id = order["id"]

        connection.execute(
            """
            DELETE FROM order_line_items
            WHERE shopify_order_id = ?;
            """,
            (order_id,),
        )

        line_item_edges = (
            order
            .get("lineItems", {})
            .get("edges", [])
        )

        for edge in line_item_edges:
            line_item = edge["node"]

            self._insert_line_item(
                connection=connection,
                order_id=order_id,
                line_item=line_item,
            )

    def _insert_line_item(
        self,
        connection,
        order_id: str,
        line_item: dict,
    ) -> None:
        """
        Insert one Shopify order line item.
        """

        variant = (
            line_item.get("variant")
            or {}
        )

        unit_price_set = (
            line_item.get(
                "originalUnitPriceSet"
            )
            or {}
        )

        shop_money = (
            unit_price_set.get("shopMoney")
            or {}
        )

        connection.execute(
            """
            INSERT INTO order_line_items (
                shopify_line_item_id,
                shopify_order_id,
                shopify_variant_id,
                sku,
                title,
                quantity,
                unit_price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                line_item["id"],
                order_id,
                variant.get("id"),
                line_item.get("sku"),
                line_item["title"],
                line_item["quantity"],
                shop_money.get("amount"),
            ),
        )

    def get_all_orders(self) -> list:
        """
        Return all stored orders,
        newest Shopify orders first.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    shopify_order_id,
                    order_name,
                    created_at,
                    updated_at,
                    currency_code,
                    total_price,
                    financial_status,
                    fulfillment_status,
                    synced_at
                FROM orders
                ORDER BY created_at DESC;
                """
            )

            return [
                dict(row)
                for row in cursor.fetchall()
            ]

    def get_all_line_items(self) -> list:
        """
        Return all stored order line items.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    shopify_line_item_id,
                    shopify_order_id,
                    shopify_variant_id,
                    sku,
                    title,
                    quantity,
                    unit_price,
                    synced_at
                FROM order_line_items
                ORDER BY shopify_order_id,
                         shopify_line_item_id;
                """
            )

            return [
                dict(row)
                for row in cursor.fetchall()
            ]

    def get_order_by_name(
        self,
        order_name: str,
    ):
        """
        Return one order by its human-readable
        Shopify order name.

        Returns None if no matching order exists.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    shopify_order_id,
                    order_name,
                    created_at,
                    updated_at,
                    currency_code,
                    total_price,
                    financial_status,
                    fulfillment_status,
                    synced_at
                FROM orders
                WHERE order_name = ?;
                """,
                (order_name,),
            )

            row = cursor.fetchone()

            if row is None:
                return None

            return dict(row)

    def get_line_items_for_order(
        self,
        shopify_order_id: str,
    ) -> list:
        """
        Return all line items belonging to one order.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    shopify_line_item_id,
                    shopify_order_id,
                    shopify_variant_id,
                    sku,
                    title,
                    quantity,
                    unit_price,
                    synced_at
                FROM order_line_items
                WHERE shopify_order_id = ?
                ORDER BY shopify_line_item_id;
                """,
                (shopify_order_id,),
            )

            return [
                dict(row)
                for row in cursor.fetchall()
            ]

    def count_orders(self) -> int:
        """
        Return the number of orders stored in SQLite.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM orders;
                """
            )

            row = cursor.fetchone()

            return row["count"]

    def count_line_items(self) -> int:
        """
        Return the number of line items stored in SQLite.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM order_line_items;
                """
            )

            row = cursor.fetchone()

            return row["count"]