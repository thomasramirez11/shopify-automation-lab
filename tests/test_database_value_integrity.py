import sqlite3
from contextlib import contextmanager

import pytest

import database.integrity as integrity_module


CREATE_TEST_SCHEMA_SQL = """
CREATE TABLE sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    started_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

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


CREATE TABLE variant_costs (
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

    updated_at TEXT NOT NULL
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
        / "value_integrity_test.db"
    )

    connection = sqlite3.connect(
        database_path
    )

    try:
        connection.executescript(
            CREATE_TEST_SCHEMA_SQL
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


def test_hardening_creates_value_integrity_triggers(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    names = set(
        integrity_module
        .get_integrity_trigger_names()
    )

    required = {
        "trg_sync_runs_terminal_immutable",
        "trg_sync_runs_counts_insert",
        "trg_sync_runs_counts_update",
        "trg_variant_costs_value_insert",
        "trg_variant_costs_value_update",
    }

    assert required.issubset(names)


def test_value_hardening_is_idempotent(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()
    integrity_module.apply_database_integrity_hardening()

    names = (
        integrity_module
        .get_integrity_trigger_names()
    )

    for trigger_name in (
        "trg_sync_runs_counts_insert",
        "trg_sync_runs_counts_update",
        "trg_variant_costs_value_insert",
        "trg_variant_costs_value_update",
    ):
        assert names.count(trigger_name) == 1


def test_preflight_reports_zero_for_valid_values(
    integrity_database,
):
    with integrity_database() as connection:
        connection.execute(
            """
            INSERT INTO sync_runs (
                status,
                products_seen,
                variants_seen
            )
            VALUES (
                'running',
                3,
                4
            );
            """
        )

        connection.execute(
            """
            INSERT INTO variant_costs (
                shopify_variant_id,
                sku,
                unit_cost,
                currency_code,
                cost_source
            )
            VALUES (
                'variant-001',
                'SKU-001',
                '4.25',
                'USD',
                'manual'
            );
            """
        )

    assert (
        integrity_module
        .get_sync_run_count_violation_count()
        == 0
    )

    assert (
        integrity_module
        .get_variant_cost_violation_count()
        == 0
    )


@pytest.mark.parametrize(
    "products_seen, variants_seen",
    [
        (-1, 4),
        (3, -1),
        (None, 4),
        (3, None),
        ("hello", 4),
        (3, "hello"),
    ],
)
def test_preflight_detects_invalid_sync_counts(
    integrity_database,
    products_seen,
    variants_seen,
):
    with integrity_database() as connection:
        connection.execute(
            """
            INSERT INTO sync_runs (
                status,
                products_seen,
                variants_seen
            )
            VALUES (
                'running',
                ?,
                ?
            );
            """,
            (
                products_seen,
                variants_seen,
            ),
        )

    assert (
        integrity_module
        .get_sync_run_count_violation_count()
        == 1
    )

    with pytest.raises(
        integrity_module.DatabaseIntegrityError,
        match="sync-count hardening",
    ):
        integrity_module.apply_database_integrity_hardening()


@pytest.mark.parametrize(
    "invalid_cost",
    [
        "-1.00",
        "",
        "   ",
        "hello",
        ".",
        "1.2.3",
        "4USD",
    ],
)
def test_preflight_detects_invalid_variant_cost(
    integrity_database,
    invalid_cost,
):
    with integrity_database() as connection:
        connection.execute(
            """
            INSERT INTO variant_costs (
                shopify_variant_id,
                sku,
                unit_cost,
                currency_code,
                cost_source
            )
            VALUES (
                'variant-001',
                'SKU-001',
                ?,
                'USD',
                'manual'
            );
            """,
            (invalid_cost,),
        )

    assert (
        integrity_module
        .get_variant_cost_violation_count()
        == 1
    )

    with pytest.raises(
        integrity_module.DatabaseIntegrityError,
        match="variant-cost hardening",
    ):
        integrity_module.apply_database_integrity_hardening()


def test_preflight_detects_blank_variant_cost_currency(
    integrity_database,
):
    with integrity_database() as connection:
        connection.execute(
            """
            INSERT INTO variant_costs (
                shopify_variant_id,
                sku,
                unit_cost,
                currency_code,
                cost_source
            )
            VALUES (
                'variant-001',
                'SKU-001',
                '4.25',
                '   ',
                'manual'
            );
            """
        )

    assert (
        integrity_module
        .get_variant_cost_violation_count()
        == 1
    )


@pytest.mark.parametrize(
    "products_seen, variants_seen",
    [
        (-1, 4),
        (3, -1),
        (None, 4),
        (3, None),
        ("hello", 4),
        (3, "hello"),
    ],
)
def test_raw_insert_rejects_invalid_sync_counts(
    integrity_database,
    products_seen,
    variants_seen,
):
    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(
        sqlite3.IntegrityError,
        match=(
            "synchronization counts must be "
            "non-negative integers"
        ),
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                INSERT INTO sync_runs (
                    status,
                    products_seen,
                    variants_seen
                )
                VALUES (
                    'running',
                    ?,
                    ?
                );
                """,
                (
                    products_seen,
                    variants_seen,
                ),
            )


def test_raw_update_rejects_negative_running_count(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    with integrity_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO sync_runs (
                status,
                products_seen,
                variants_seen
            )
            VALUES (
                'running',
                3,
                4
            );
            """
        )

        run_id = cursor.lastrowid

    with pytest.raises(
        sqlite3.IntegrityError,
        match=(
            "synchronization counts must be "
            "non-negative integers"
        ),
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE sync_runs
                SET products_seen = -1
                WHERE id = ?;
                """,
                (run_id,),
            )


@pytest.mark.parametrize(
    "products_seen, variants_seen",
    [
        (0, 0),
        (3, 4),
        (100, 250),
    ],
)
def test_valid_sync_counts_are_allowed(
    integrity_database,
    products_seen,
    variants_seen,
):
    integrity_module.apply_database_integrity_hardening()

    with integrity_database() as connection:
        connection.execute(
            """
            INSERT INTO sync_runs (
                status,
                products_seen,
                variants_seen
            )
            VALUES (
                'running',
                ?,
                ?
            );
            """,
            (
                products_seen,
                variants_seen,
            ),
        )


@pytest.mark.parametrize(
    "valid_cost",
    [
        "0",
        "0.00",
        "4.25",
        ".50",
        "10.",
        "0004.250",
    ],
)
def test_valid_plain_decimal_variant_costs_are_allowed(
    integrity_database,
    valid_cost,
):
    integrity_module.apply_database_integrity_hardening()

    with integrity_database() as connection:
        connection.execute(
            """
            INSERT INTO variant_costs (
                shopify_variant_id,
                sku,
                unit_cost,
                currency_code,
                cost_source
            )
            VALUES (
                ?,
                'SKU-001',
                ?,
                'USD',
                'manual'
            );
            """,
            (
                f"variant-{valid_cost}",
                valid_cost,
            ),
        )


@pytest.mark.parametrize(
    "invalid_cost",
    [
        "-1",
        "-1.00",
        "",
        " ",
        "hello",
        ".",
        "1.2.3",
        "4USD",
        "+4.25",
        "1e2",
    ],
)
def test_raw_insert_rejects_invalid_variant_cost(
    integrity_database,
    invalid_cost,
):
    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(
        sqlite3.IntegrityError,
        match=(
            "variant cost must use a "
            "non-negative decimal and currency"
        ),
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                INSERT INTO variant_costs (
                    shopify_variant_id,
                    sku,
                    unit_cost,
                    currency_code,
                    cost_source
                )
                VALUES (
                    'variant-001',
                    'SKU-001',
                    ?,
                    'USD',
                    'manual'
                );
                """,
                (invalid_cost,),
            )


def test_raw_insert_rejects_blank_currency(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                INSERT INTO variant_costs (
                    shopify_variant_id,
                    sku,
                    unit_cost,
                    currency_code,
                    cost_source
                )
                VALUES (
                    'variant-001',
                    'SKU-001',
                    '4.25',
                    '   ',
                    'manual'
                );
                """
            )


def test_raw_update_rejects_invalid_variant_cost(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    with integrity_database() as connection:
        connection.execute(
            """
            INSERT INTO variant_costs (
                shopify_variant_id,
                sku,
                unit_cost,
                currency_code,
                cost_source
            )
            VALUES (
                'variant-001',
                'SKU-001',
                '4.25',
                'USD',
                'manual'
            );
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE variant_costs
                SET unit_cost = '-5.00'
                WHERE shopify_variant_id = 'variant-001';
                """
            )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT unit_cost
            FROM variant_costs
            WHERE shopify_variant_id = 'variant-001';
            """
        ).fetchone()

    assert stored["unit_cost"] == "4.25"
