import logging

from database.connection import get_db_connection


logger = logging.getLogger(__name__)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
    shopify_product_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS variants (
    shopify_variant_id TEXT PRIMARY KEY,

    shopify_product_id TEXT NOT NULL,

    title TEXT NOT NULL,

    sku TEXT,

    price TEXT,

    inventory_quantity INTEGER,

    inventory_item_id TEXT UNIQUE,

    synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (shopify_product_id)
        REFERENCES products(shopify_product_id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS variant_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    shopify_variant_id TEXT NOT NULL,

    field_name TEXT NOT NULL
        CHECK (
            field_name IN (
                'price',
                'inventory_quantity'
            )
        ),

    old_value TEXT,

    new_value TEXT,

    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (shopify_variant_id)
        REFERENCES variants(shopify_variant_id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    completed_at TEXT,

    status TEXT NOT NULL
        CHECK (
            status IN (
                'running',
                'success',
                'failed'
            )
        ),

    products_seen INTEGER DEFAULT 0,

    variants_seen INTEGER DEFAULT 0,

    error_message TEXT
);


CREATE TABLE IF NOT EXISTS orders (
    shopify_order_id TEXT PRIMARY KEY,

    order_name TEXT NOT NULL,

    created_at TEXT NOT NULL,

    updated_at TEXT NOT NULL,

    currency_code TEXT NOT NULL,

    total_price TEXT NOT NULL,

    financial_status TEXT,

    fulfillment_status TEXT,

    synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS order_line_items (
    shopify_line_item_id TEXT PRIMARY KEY,

    shopify_order_id TEXT NOT NULL,

    shopify_variant_id TEXT,

    sku TEXT,

    title TEXT NOT NULL,

    quantity INTEGER NOT NULL
        CHECK (quantity >= 0),

    unit_price TEXT,

    synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (shopify_order_id)
        REFERENCES orders(shopify_order_id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS variant_costs (
    shopify_variant_id TEXT PRIMARY KEY,

    sku TEXT,

    unit_cost TEXT NOT NULL,

    currency_code TEXT NOT NULL,

    cost_source TEXT NOT NULL DEFAULT 'manual'
        CHECK (
            cost_source IN (
                'manual',
                'supplier'
            )
        ),

    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS order_line_item_profit_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    shopify_line_item_id TEXT NOT NULL UNIQUE,

    shopify_order_id TEXT NOT NULL,

    shopify_variant_id TEXT,

    sku TEXT,

    quantity INTEGER NOT NULL
        CHECK (quantity >= 0),

    currency_code TEXT NOT NULL,

    unit_sale_price TEXT NOT NULL,

    unit_cost TEXT NOT NULL,

    line_revenue TEXT NOT NULL,

    line_cost TEXT NOT NULL,

    estimated_gross_profit TEXT NOT NULL,

    gross_margin_percent TEXT,

    cost_source TEXT NOT NULL,

    calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE INDEX IF NOT EXISTS idx_variants_product_id
ON variants(shopify_product_id);


CREATE INDEX IF NOT EXISTS idx_variants_sku
ON variants(sku);


CREATE INDEX IF NOT EXISTS idx_variant_changes_variant_id
ON variant_changes(shopify_variant_id);


CREATE INDEX IF NOT EXISTS idx_orders_created_at
ON orders(created_at);


CREATE INDEX IF NOT EXISTS idx_order_line_items_order_id
ON order_line_items(shopify_order_id);


CREATE INDEX IF NOT EXISTS idx_order_line_items_variant_id
ON order_line_items(shopify_variant_id);


CREATE INDEX IF NOT EXISTS idx_order_line_items_sku
ON order_line_items(sku);


CREATE INDEX IF NOT EXISTS idx_variant_costs_sku
ON variant_costs(sku);


CREATE INDEX IF NOT EXISTS idx_profit_snapshots_order_id
ON order_line_item_profit_snapshots(shopify_order_id);


CREATE INDEX IF NOT EXISTS idx_profit_snapshots_variant_id
ON order_line_item_profit_snapshots(shopify_variant_id);


CREATE INDEX IF NOT EXISTS idx_profit_snapshots_sku
ON order_line_item_profit_snapshots(sku);
"""


def initialize_database():
    """
    Create the SQLite tables and indexes required by the application.
    """

    with get_db_connection() as connection:
        connection.executescript(SCHEMA_SQL)

    logger.info(
        "SQLite database initialized successfully."
    )


def get_table_names():
    """
    Return all user-created SQLite tables.
    """

    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
            """
        )

        return [
            row["name"]
            for row in cursor.fetchall()
        ]


if __name__ == "__main__":
    initialize_database()

    tables = get_table_names()

    print("Database initialized successfully.")
    print("Tables:")

    for table in tables:
        print(f"  - {table}")