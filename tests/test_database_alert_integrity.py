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


CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    alert_type TEXT NOT NULL
        CHECK (
            alert_type IN (
                'new_order',
                'missing_cost',
                'low_inventory',
                'sync_failure'
            )
        ),

    severity TEXT NOT NULL
        CHECK (
            severity IN (
                'info',
                'warning',
                'error',
                'critical'
            )
        ),

    status TEXT NOT NULL DEFAULT 'open'
        CHECK (
            status IN (
                'open',
                'resolved'
            )
        ),

    dedupe_key TEXT NOT NULL,

    title TEXT NOT NULL,

    message TEXT NOT NULL,

    entity_type TEXT,

    entity_id TEXT,

    occurrence_count INTEGER NOT NULL DEFAULT 1
        CHECK (occurrence_count >= 1),

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    last_seen_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    resolved_at TEXT
);
"""


@pytest.fixture
def integrity_database(
    tmp_path,
    monkeypatch,
):
    database_path = (
        tmp_path
        / "integrity_test.db"
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


def insert_valid_open_alert(
    integrity_database,
    *,
    dedupe_key="test:open",
):
    with integrity_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO alerts (
                alert_type,
                severity,
                status,
                dedupe_key,
                title,
                message,
                resolved_at
            )
            VALUES (
                'low_inventory',
                'warning',
                'open',
                ?,
                'Low inventory',
                'Inventory is low.',
                NULL
            );
            """,
            (dedupe_key,),
        )

        return cursor.lastrowid


def test_hardening_creates_all_integrity_triggers(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    trigger_names = (
        integrity_module
        .get_integrity_trigger_names()
    )

    required_triggers = {
        "trg_alerts_state_consistency_insert",
        "trg_alerts_state_consistency_update",
        "trg_sync_runs_terminal_immutable",
    }

    assert required_triggers.issubset(
        set(trigger_names)
    )


def test_hardening_remains_idempotent(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()
    integrity_module.apply_database_integrity_hardening()

    trigger_names = (
        integrity_module
        .get_integrity_trigger_names()
    )

    for trigger_name in (
        "trg_alerts_state_consistency_insert",
        "trg_alerts_state_consistency_update",
        "trg_sync_runs_terminal_immutable",
    ):
        assert trigger_names.count(
            trigger_name
        ) == 1


def test_preflight_reports_zero_for_valid_alert_history(
    integrity_database,
):
    insert_valid_open_alert(
        integrity_database
    )

    assert (
        integrity_module
        .get_alert_state_violation_count()
        == 0
    )


def test_preflight_rejects_existing_open_alert_with_resolved_timestamp(
    integrity_database,
):
    with integrity_database() as connection:
        connection.execute(
            """
            INSERT INTO alerts (
                alert_type,
                severity,
                status,
                dedupe_key,
                title,
                message,
                resolved_at
            )
            VALUES (
                'low_inventory',
                'warning',
                'open',
                'bad:open',
                'Bad state',
                'Bad state',
                CURRENT_TIMESTAMP
            );
            """
        )

    assert (
        integrity_module
        .get_alert_state_violation_count()
        == 1
    )

    with pytest.raises(
        integrity_module.DatabaseIntegrityError,
        match="1 existing alert row",
    ):
        integrity_module.apply_database_integrity_hardening()


def test_preflight_rejects_existing_resolved_alert_without_timestamp(
    integrity_database,
):
    with integrity_database() as connection:
        connection.execute(
            """
            INSERT INTO alerts (
                alert_type,
                severity,
                status,
                dedupe_key,
                title,
                message,
                resolved_at
            )
            VALUES (
                'missing_cost',
                'warning',
                'resolved',
                'bad:resolved',
                'Bad state',
                'Bad state',
                NULL
            );
            """
        )

    with pytest.raises(
        integrity_module.DatabaseIntegrityError,
        match="1 existing alert row",
    ):
        integrity_module.apply_database_integrity_hardening()


def test_valid_open_alert_insert_is_allowed(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    alert_id = insert_valid_open_alert(
        integrity_database
    )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT status, resolved_at
            FROM alerts
            WHERE id = ?;
            """,
            (alert_id,),
        ).fetchone()

    assert stored["status"] == "open"
    assert stored["resolved_at"] is None


def test_valid_resolved_alert_insert_is_allowed(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    with integrity_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO alerts (
                alert_type,
                severity,
                status,
                dedupe_key,
                title,
                message,
                resolved_at
            )
            VALUES (
                'missing_cost',
                'warning',
                'resolved',
                'valid:resolved',
                'Resolved alert',
                'Resolved alert',
                CURRENT_TIMESTAMP
            );
            """
        )

        alert_id = cursor.lastrowid

        stored = connection.execute(
            """
            SELECT status, resolved_at
            FROM alerts
            WHERE id = ?;
            """,
            (alert_id,),
        ).fetchone()

    assert stored["status"] == "resolved"
    assert stored["resolved_at"] is not None


def test_open_alert_with_resolved_timestamp_is_rejected(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(
        sqlite3.IntegrityError,
        match=(
            "alert status and resolved_at "
            "are inconsistent"
        ),
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                INSERT INTO alerts (
                    alert_type,
                    severity,
                    status,
                    dedupe_key,
                    title,
                    message,
                    resolved_at
                )
                VALUES (
                    'low_inventory',
                    'warning',
                    'open',
                    'invalid:open',
                    'Invalid alert',
                    'Invalid alert',
                    CURRENT_TIMESTAMP
                );
                """
            )


@pytest.mark.parametrize(
    "resolved_at",
    [
        None,
        "",
        "   ",
    ],
)
def test_resolved_alert_requires_non_blank_timestamp(
    integrity_database,
    resolved_at,
):
    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(
        sqlite3.IntegrityError,
        match=(
            "alert status and resolved_at "
            "are inconsistent"
        ),
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                INSERT INTO alerts (
                    alert_type,
                    severity,
                    status,
                    dedupe_key,
                    title,
                    message,
                    resolved_at
                )
                VALUES (
                    'missing_cost',
                    'warning',
                    'resolved',
                    'invalid:resolved',
                    'Invalid alert',
                    'Invalid alert',
                    ?
                );
                """,
                (resolved_at,),
            )


def test_normal_open_to_resolved_transition_is_allowed(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    alert_id = insert_valid_open_alert(
        integrity_database
    )

    with integrity_database() as connection:
        connection.execute(
            """
            UPDATE alerts

            SET
                status = 'resolved',
                resolved_at = CURRENT_TIMESTAMP

            WHERE id = ?;
            """,
            (alert_id,),
        )

        stored = connection.execute(
            """
            SELECT status, resolved_at
            FROM alerts
            WHERE id = ?;
            """,
            (alert_id,),
        ).fetchone()

    assert stored["status"] == "resolved"
    assert stored["resolved_at"] is not None


def test_update_cannot_resolve_without_timestamp(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    alert_id = insert_valid_open_alert(
        integrity_database
    )

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE alerts
                SET status = 'resolved'
                WHERE id = ?;
                """,
                (alert_id,),
            )


def test_update_cannot_reopen_while_resolved_timestamp_remains(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    alert_id = insert_valid_open_alert(
        integrity_database
    )

    with integrity_database() as connection:
        connection.execute(
            """
            UPDATE alerts

            SET
                status = 'resolved',
                resolved_at = CURRENT_TIMESTAMP

            WHERE id = ?;
            """,
            (alert_id,),
        )

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE alerts
                SET status = 'open'
                WHERE id = ?;
                """,
                (alert_id,),
            )


def test_touching_open_alert_remains_allowed(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    alert_id = insert_valid_open_alert(
        integrity_database
    )

    with integrity_database() as connection:
        connection.execute(
            """
            UPDATE alerts

            SET
                occurrence_count = occurrence_count + 1,
                last_seen_at = CURRENT_TIMESTAMP,
                message = 'Inventory is still low.'

            WHERE id = ?;
            """,
            (alert_id,),
        )

        stored = connection.execute(
            """
            SELECT
                status,
                resolved_at,
                occurrence_count,
                message

            FROM alerts

            WHERE id = ?;
            """,
            (alert_id,),
        ).fetchone()

    assert stored["status"] == "open"
    assert stored["resolved_at"] is None
    assert stored["occurrence_count"] == 2

    assert (
        stored["message"]
        == "Inventory is still low."
    )

