import sqlite3
from contextlib import contextmanager

import pytest

import database.integrity as integrity_module


CREATE_PROFIT_SNAPSHOT_TABLE_SQL = """
CREATE TABLE order_line_item_profit_snapshots (
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

    calculated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest.fixture
def integrity_database(
    tmp_path,
    monkeypatch,
):
    database_path = (
        tmp_path
        / "profit_snapshot_integrity.db"
    )

    connection = sqlite3.connect(
        database_path
    )

    try:
        connection.executescript(
            CREATE_PROFIT_SNAPSHOT_TABLE_SQL
        )
        connection.commit()
    finally:
        connection.close()

    @contextmanager
    def temporary_db_connection():
        connection = sqlite3.connect(
            database_path
        )

        connection.row_factory = sqlite3.Row

        try:
            yield connection
            connection.commit()

        except sqlite3.Error:
            connection.rollback()
            raise

        finally:
            connection.close()

    monkeypatch.setattr(
        integrity_module,
        "get_db_connection",
        temporary_db_connection,
    )

    return temporary_db_connection


def insert_snapshot(
    integrity_database,
    *,
    line_item_id="line-001",
):
    with integrity_database() as connection:
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
            VALUES (
                ?,
                'order-001',
                'variant-001',
                'SKU-001',
                1,
                'USD',
                '10.00',
                '4.25',
                '10.00',
                '4.25',
                '5.75',
                '57.50',
                'manual'
            );
            """,
            (line_item_id,),
        )

        return cursor.lastrowid


def test_hardening_creates_snapshot_immutability_triggers(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    names = (
        integrity_module
        .get_integrity_trigger_names()
    )

    assert names.count(
        "trg_profit_snapshots_immutable_update"
    ) == 1

    assert names.count(
        "trg_profit_snapshots_immutable_delete"
    ) == 1


def test_snapshot_hardening_is_idempotent(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()
    integrity_module.apply_database_integrity_hardening()

    names = (
        integrity_module
        .get_integrity_trigger_names()
    )

    assert names.count(
        "trg_profit_snapshots_immutable_update"
    ) == 1

    assert names.count(
        "trg_profit_snapshots_immutable_delete"
    ) == 1


def test_new_snapshot_insert_remains_allowed(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    snapshot_id = insert_snapshot(
        integrity_database
    )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT *
            FROM order_line_item_profit_snapshots
            WHERE id = ?;
            """,
            (snapshot_id,),
        ).fetchone()

    assert stored is not None
    assert stored["unit_cost"] == "4.25"
    assert stored["estimated_gross_profit"] == "5.75"


def test_raw_update_of_historical_snapshot_is_rejected(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    snapshot_id = insert_snapshot(
        integrity_database
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="historical profit snapshots are immutable",
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE order_line_item_profit_snapshots
                SET unit_cost = '0.01'
                WHERE id = ?;
                """,
                (snapshot_id,),
            )


def test_failed_update_leaves_snapshot_unchanged(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    snapshot_id = insert_snapshot(
        integrity_database
    )

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE order_line_item_profit_snapshots
                SET
                    line_cost = '0.01',
                    estimated_gross_profit = '9.99'
                WHERE id = ?;
                """,
                (snapshot_id,),
            )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT
                line_cost,
                estimated_gross_profit
            FROM order_line_item_profit_snapshots
            WHERE id = ?;
            """,
            (snapshot_id,),
        ).fetchone()

    assert stored["line_cost"] == "4.25"
    assert stored["estimated_gross_profit"] == "5.75"


def test_raw_delete_of_historical_snapshot_is_rejected(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    snapshot_id = insert_snapshot(
        integrity_database
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="historical profit snapshots are immutable",
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                DELETE FROM order_line_item_profit_snapshots
                WHERE id = ?;
                """,
                (snapshot_id,),
            )


def test_failed_delete_preserves_historical_snapshot(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    snapshot_id = insert_snapshot(
        integrity_database
    )

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                DELETE FROM order_line_item_profit_snapshots
                WHERE id = ?;
                """,
                (snapshot_id,),
            )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT *
            FROM order_line_item_profit_snapshots
            WHERE id = ?;
            """,
            (snapshot_id,),
        ).fetchone()

    assert stored is not None


def test_existing_snapshot_becomes_protected_after_hardening(
    integrity_database,
):
    snapshot_id = insert_snapshot(
        integrity_database
    )

    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE order_line_item_profit_snapshots
                SET currency_code = 'COP'
                WHERE id = ?;
                """,
                (snapshot_id,),
            )
