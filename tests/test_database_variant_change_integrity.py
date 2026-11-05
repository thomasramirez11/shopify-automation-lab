import sqlite3
from contextlib import contextmanager

import pytest

import database.integrity as integrity_module


CREATE_VARIANT_HISTORY_SCHEMA_SQL = """
CREATE TABLE products (
    shopify_product_id TEXT PRIMARY KEY,

    title TEXT NOT NULL
);


CREATE TABLE variants (
    shopify_variant_id TEXT PRIMARY KEY,

    shopify_product_id TEXT NOT NULL,

    title TEXT NOT NULL,

    FOREIGN KEY (
        shopify_product_id
    )
        REFERENCES products(
            shopify_product_id
        )
        ON DELETE CASCADE
);


CREATE TABLE variant_changes (
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

    detected_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (
        shopify_variant_id
    )
        REFERENCES variants(
            shopify_variant_id
        )
        ON DELETE CASCADE
);
"""


@pytest.fixture
def integrity_database(
    tmp_path,
    monkeypatch,
):
    database_path = (
        tmp_path
        / "variant_change_integrity.db"
    )

    connection = sqlite3.connect(
        database_path
    )

    connection.execute(
        "PRAGMA foreign_keys = ON;"
    )

    try:
        connection.executescript(
            CREATE_VARIANT_HISTORY_SCHEMA_SQL
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

        connection.execute(
            "PRAGMA foreign_keys = ON;"
        )

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


def create_variant(
    integrity_database,
    *,
    product_id="product-001",
    variant_id="variant-001",
):
    with integrity_database() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO products (
                shopify_product_id,
                title
            )
            VALUES (?, 'Test product');
            """,
            (product_id,),
        )

        connection.execute(
            """
            INSERT INTO variants (
                shopify_variant_id,
                shopify_product_id,
                title
            )
            VALUES (
                ?,
                ?,
                'Default Title'
            );
            """,
            (
                variant_id,
                product_id,
            ),
        )


def insert_variant_change(
    integrity_database,
    *,
    variant_id="variant-001",
):
    with integrity_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO variant_changes (
                shopify_variant_id,
                field_name,
                old_value,
                new_value
            )
            VALUES (
                ?,
                'inventory_quantity',
                '10',
                '2'
            );
            """,
            (variant_id,),
        )

        return cursor.lastrowid


def test_hardening_creates_variant_history_triggers(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    names = (
        integrity_module
        .get_integrity_trigger_names()
    )

    assert names.count(
        "trg_variant_changes_immutable_update"
    ) == 1

    assert names.count(
        "trg_variant_changes_immutable_delete"
    ) == 1


def test_variant_history_hardening_is_idempotent(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()
    integrity_module.apply_database_integrity_hardening()

    names = (
        integrity_module
        .get_integrity_trigger_names()
    )

    assert names.count(
        "trg_variant_changes_immutable_update"
    ) == 1

    assert names.count(
        "trg_variant_changes_immutable_delete"
    ) == 1


def test_new_variant_change_insert_remains_allowed(
    integrity_database,
):
    create_variant(
        integrity_database
    )

    integrity_module.apply_database_integrity_hardening()

    change_id = insert_variant_change(
        integrity_database
    )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT *
            FROM variant_changes
            WHERE id = ?;
            """,
            (change_id,),
        ).fetchone()

    assert stored is not None
    assert stored["old_value"] == "10"
    assert stored["new_value"] == "2"


def test_multiple_historical_changes_remain_allowed(
    integrity_database,
):
    create_variant(
        integrity_database
    )

    integrity_module.apply_database_integrity_hardening()

    first_id = insert_variant_change(
        integrity_database
    )

    with integrity_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO variant_changes (
                shopify_variant_id,
                field_name,
                old_value,
                new_value
            )
            VALUES (
                'variant-001',
                'inventory_quantity',
                '2',
                '8'
            );
            """
        )

        second_id = cursor.lastrowid

    assert first_id != second_id


def test_raw_update_of_variant_history_is_rejected(
    integrity_database,
):
    create_variant(
        integrity_database
    )

    change_id = insert_variant_change(
        integrity_database
    )

    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(
        sqlite3.IntegrityError,
        match=(
            "historical variant changes "
            "are immutable"
        ),
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE variant_changes
                SET new_value = '999'
                WHERE id = ?;
                """,
                (change_id,),
            )


def test_failed_update_preserves_original_history(
    integrity_database,
):
    create_variant(
        integrity_database
    )

    change_id = insert_variant_change(
        integrity_database
    )

    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE variant_changes
                SET
                    old_value = '0',
                    new_value = '999'
                WHERE id = ?;
                """,
                (change_id,),
            )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT old_value, new_value
            FROM variant_changes
            WHERE id = ?;
            """,
            (change_id,),
        ).fetchone()

    assert stored["old_value"] == "10"
    assert stored["new_value"] == "2"


def test_direct_delete_of_variant_history_is_rejected(
    integrity_database,
):
    create_variant(
        integrity_database
    )

    change_id = insert_variant_change(
        integrity_database
    )

    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(
        sqlite3.IntegrityError,
        match=(
            "historical variant changes "
            "are immutable"
        ),
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                DELETE FROM variant_changes
                WHERE id = ?;
                """,
                (change_id,),
            )


def test_parent_variant_delete_is_blocked_when_history_exists(
    integrity_database,
):
    create_variant(
        integrity_database
    )

    insert_variant_change(
        integrity_database
    )

    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(
        sqlite3.IntegrityError,
        match=(
            "historical variant changes "
            "are immutable"
        ),
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                DELETE FROM variants
                WHERE shopify_variant_id = 'variant-001';
                """
            )

    with integrity_database() as connection:
        variant = connection.execute(
            """
            SELECT *
            FROM variants
            WHERE shopify_variant_id = 'variant-001';
            """
        ).fetchone()

        change_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM variant_changes
            WHERE shopify_variant_id = 'variant-001';
            """
        ).fetchone()["count"]

    assert variant is not None
    assert change_count == 1


def test_variant_without_history_can_still_be_deleted(
    integrity_database,
):
    create_variant(
        integrity_database,
        variant_id="variant-no-history",
    )

    integrity_module.apply_database_integrity_hardening()

    with integrity_database() as connection:
        connection.execute(
            """
            DELETE FROM variants
            WHERE shopify_variant_id = 'variant-no-history';
            """
        )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT *
            FROM variants
            WHERE shopify_variant_id = 'variant-no-history';
            """
        ).fetchone()

    assert stored is None


def test_existing_history_becomes_protected_after_hardening(
    integrity_database,
):
    create_variant(
        integrity_database
    )

    change_id = insert_variant_change(
        integrity_database
    )

    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                DELETE FROM variant_changes
                WHERE id = ?;
                """,
                (change_id,),
            )
