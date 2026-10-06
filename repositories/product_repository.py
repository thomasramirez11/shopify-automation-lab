import logging

from database.connection import get_db_connection


logger = logging.getLogger(__name__)


class ProductRepository:
    """
    Handles database operations for Shopify products and variants.
    """

    def save_product(self, product: dict) -> None:
        """
        Save one Shopify product and all of its variants.

        Existing products and variants are updated instead of duplicated.
        """

        with get_db_connection() as connection:
            self._insert_product(connection, product)

            variant_edges = (
                product
                .get("variants", {})
                .get("edges", [])
            )

            for edge in variant_edges:
                variant = edge["node"]

                self._insert_variant(
                    connection=connection,
                    product_id=product["id"],
                    variant=variant,
                )

        logger.info(
            "Saved product '%s' and its variants.",
            product["title"],
        )

    def _insert_product(
        self,
        connection,
        product: dict,
    ) -> None:
        """
        Insert a new product or update it if it already exists.
        """

        connection.execute(
            """
            INSERT INTO products (
                shopify_product_id,
                title
            )
            VALUES (?, ?)

            ON CONFLICT(shopify_product_id)
            DO UPDATE SET
                title = excluded.title,
                synced_at = CURRENT_TIMESTAMP;
            """,
            (
                product["id"],
                product["title"],
            ),
        )

    def _get_existing_variant(
        self,
        connection,
        variant_id: str,
    ):
        """
        Return the current stored variant before synchronization.

        Returns None if the variant has never been stored before.
        """

        cursor = connection.execute(
            """
            SELECT
                shopify_variant_id,
                price,
                inventory_quantity
            FROM variants
            WHERE shopify_variant_id = ?;
            """,
            (variant_id,),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return dict(row)

    def _detect_variant_changes(
        self,
        connection,
        existing_variant: dict,
        incoming_variant: dict,
    ) -> None:
        """
        Compare the existing SQLite state with the latest Shopify state.
        """

        comparisons = {
            "price": incoming_variant.get("price"),
            "inventory_quantity": incoming_variant.get(
                "inventoryQuantity"
            ),
        }

        for field_name, new_value in comparisons.items():
            old_value = existing_variant[field_name]

            if old_value != new_value:
                self._record_variant_change(
                    connection=connection,
                    variant_id=incoming_variant["id"],
                    field_name=field_name,
                    old_value=old_value,
                    new_value=new_value,
                )

    def _record_variant_change(
        self,
        connection,
        variant_id: str,
        field_name: str,
        old_value,
        new_value,
    ) -> None:
        """
        Store one detected variant change in variant_changes.
        """

        connection.execute(
            """
            INSERT INTO variant_changes (
                shopify_variant_id,
                field_name,
                old_value,
                new_value
            )
            VALUES (?, ?, ?, ?);
            """,
            (
                variant_id,
                field_name,
                None if old_value is None else str(old_value),
                None if new_value is None else str(new_value),
            ),
        )
    
    def _insert_variant(
        self,
        connection,
        product_id: str,
        variant: dict,
    ) -> None:
        """
        Detect changes, then insert or update a Shopify variant.
        """

        inventory_item = variant.get("inventoryItem") or {}

        existing_variant = self._get_existing_variant(
            connection=connection,
            variant_id=variant["id"],
        )

        if existing_variant is not None:
            self._detect_variant_changes(
                connection=connection,
                existing_variant=existing_variant,
                incoming_variant=variant,
            )

        connection.execute(
            """
            INSERT INTO variants (
                shopify_variant_id,
                shopify_product_id,
                title,
                sku,
                price,
                inventory_quantity,
                inventory_item_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(shopify_variant_id)
            DO UPDATE SET
                shopify_product_id = excluded.shopify_product_id,
                title = excluded.title,
                sku = excluded.sku,
                price = excluded.price,
                inventory_quantity = excluded.inventory_quantity,
                inventory_item_id = excluded.inventory_item_id,
                synced_at = CURRENT_TIMESTAMP;
            """,
            (
                variant["id"],
                product_id,
                variant["title"],
                variant.get("sku"),
                variant.get("price"),
                variant.get("inventoryQuantity"),
                inventory_item.get("id"),
            ),
        )    

    def get_variant_changes_by_sku(
        self,
        sku: str,
    ) -> list:
        """
        Return recorded price and inventory changes for a SKU.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    vc.id,
                    v.sku,
                    vc.field_name,
                    vc.old_value,
                    vc.new_value,
                    vc.detected_at
                FROM variant_changes AS vc

                INNER JOIN variants AS v
                    ON vc.shopify_variant_id =
                    v.shopify_variant_id

                WHERE v.sku = ?

                ORDER BY vc.id;
                """,
                (sku,),
            )

            return [
                dict(row)
                for row in cursor.fetchall()
            ]

    def get_all_products(self) -> list:
        """
        Return all products currently stored in SQLite.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    shopify_product_id,
                    title,
                    synced_at
                FROM products
                ORDER BY title;
                """
            )

            return [
                dict(row)
                for row in cursor.fetchall()
            ]

    def get_all_variants(self) -> list:
        """
        Return all variants currently stored in SQLite.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    shopify_variant_id,
                    shopify_product_id,
                    title,
                    sku,
                    price,
                    inventory_quantity,
                    inventory_item_id,
                    synced_at
                FROM variants
                ORDER BY title;
                """
            )

            return [
                dict(row)
                for row in cursor.fetchall()
            ]

    def get_variant_by_sku(self, sku: str):
        """
        Return one variant by SKU.

        Returns None if no matching variant exists.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    shopify_variant_id,
                    shopify_product_id,
                    title,
                    sku,
                    price,
                    inventory_quantity,
                    inventory_item_id,
                    synced_at
                FROM variants
                WHERE sku = ?;
                """,
                (sku,),
            )

            row = cursor.fetchone()

            if row is None:
                return None

            return dict(row)