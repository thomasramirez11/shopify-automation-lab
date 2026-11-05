import sqlite3
from contextlib import contextmanager

import pytest

import database.integrity as integrity_module


CREATE_SYNC_RUNS_TABLE_SQL = """
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
            CREATE_SYNC_RUNS_TABLE_SQL
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


def test_hardening_creates_terminal_immutability_trigger(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    trigger_names = (
        integrity_module
        .get_integrity_trigger_names()
    )

    assert (
        "trg_sync_runs_terminal_immutable"
        in trigger_names
    )


def test_hardening_is_idempotent(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()
    integrity_module.apply_database_integrity_hardening()

    trigger_names = (
        integrity_module
        .get_integrity_trigger_names()
    )

    assert trigger_names.count(
        "trg_sync_runs_terminal_immutable"
    ) == 1


def test_running_run_can_transition_to_success(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    with integrity_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO sync_runs (
                status
            )
            VALUES ('running');
            """
        )

        run_id = cursor.lastrowid

        connection.execute(
            """
            UPDATE sync_runs
            SET
                status = 'success',
                completed_at = CURRENT_TIMESTAMP,
                products_seen = 3,
                variants_seen = 4
            WHERE id = ?;
            """,
            (run_id,),
        )

        stored = connection.execute(
            """
            SELECT *
            FROM sync_runs
            WHERE id = ?;
            """,
            (run_id,),
        ).fetchone()

    assert stored["status"] == "success"
    assert stored["products_seen"] == 3
    assert stored["variants_seen"] == 4


def test_running_run_can_transition_to_failed(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    with integrity_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO sync_runs (
                status
            )
            VALUES ('running');
            """
        )

        run_id = cursor.lastrowid

        connection.execute(
            """
            UPDATE sync_runs
            SET
                status = 'failed',
                completed_at = CURRENT_TIMESTAMP,
                error_message = 'test failure'
            WHERE id = ?;
            """,
            (run_id,),
        )

        stored = connection.execute(
            """
            SELECT *
            FROM sync_runs
            WHERE id = ?;
            """,
            (run_id,),
        ).fetchone()

    assert stored["status"] == "failed"
    assert stored["error_message"] == "test failure"


def test_success_run_cannot_be_rewritten_with_raw_sql(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    with integrity_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO sync_runs (
                status,
                completed_at,
                products_seen,
                variants_seen
            )
            VALUES (
                'success',
                CURRENT_TIMESTAMP,
                3,
                4
            );
            """
        )

        run_id = cursor.lastrowid

    with pytest.raises(
        sqlite3.IntegrityError,
        match=(
            "terminal synchronization "
            "runs are immutable"
        ),
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE sync_runs
                SET products_seen = 999
                WHERE id = ?;
                """,
                (run_id,),
            )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT *
            FROM sync_runs
            WHERE id = ?;
            """,
            (run_id,),
        ).fetchone()

    assert stored["status"] == "success"
    assert stored["products_seen"] == 3
    assert stored["variants_seen"] == 4


def test_failed_run_cannot_transition_to_success_with_raw_sql(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    with integrity_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO sync_runs (
                status,
                completed_at,
                error_message
            )
            VALUES (
                'failed',
                CURRENT_TIMESTAMP,
                'original failure'
            );
            """
        )

        run_id = cursor.lastrowid

    with pytest.raises(
        sqlite3.IntegrityError,
        match=(
            "terminal synchronization "
            "runs are immutable"
        ),
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE sync_runs
                SET
                    status = 'success',
                    error_message = NULL
                WHERE id = ?;
                """,
                (run_id,),
            )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT *
            FROM sync_runs
            WHERE id = ?;
            """,
            (run_id,),
        ).fetchone()

    assert stored["status"] == "failed"

    assert (
        stored["error_message"]
        == "original failure"
    )


def test_existing_terminal_row_becomes_protected_after_hardening(
    integrity_database,
):
    with integrity_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO sync_runs (
                status,
                completed_at,
                products_seen,
                variants_seen
            )
            VALUES (
                'success',
                CURRENT_TIMESTAMP,
                3,
                4
            );
            """
        )

        run_id = cursor.lastrowid

    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE sync_runs
                SET variants_seen = 999
                WHERE id = ?;
                """,
                (run_id,),
            )
