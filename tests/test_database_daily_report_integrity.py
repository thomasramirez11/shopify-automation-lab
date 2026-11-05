import json
import sqlite3
from contextlib import contextmanager

import pytest

import database.integrity as integrity_module


CREATE_DAILY_REPORTS_TABLE_SQL = """
CREATE TABLE daily_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    business_date TEXT NOT NULL,

    report_timezone TEXT NOT NULL,

    generated_at_utc TEXT NOT NULL,

    health_status TEXT NOT NULL
        CHECK (
            health_status IN (
                'healthy',
                'attention',
                'critical'
            )
        ),

    report_json TEXT NOT NULL,

    created_at TEXT NOT NULL
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
        / "daily_report_integrity.db"
    )

    connection = sqlite3.connect(
        database_path
    )

    try:
        connection.executescript(
            CREATE_DAILY_REPORTS_TABLE_SQL
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


def insert_daily_report(
    integrity_database,
    *,
    generated_at_utc="2026-11-04T14:00:00+00:00",
    health_status="attention",
):
    report = {
        "generated_at_utc":
            generated_at_utc,

        "report_context": {
            "timezone":
                "America/Bogota",

            "local_date":
                "2026-11-04",
        },

        "health": {
            "status":
                health_status,

            "headline":
                "Test report",
        },
    }

    with integrity_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO daily_reports (
                business_date,
                report_timezone,
                generated_at_utc,
                health_status,
                report_json
            )
            VALUES (
                '2026-11-04',
                'America/Bogota',
                ?,
                ?,
                ?
            );
            """,
            (
                generated_at_utc,
                health_status,
                json.dumps(
                    report,
                    sort_keys=True,
                ),
            ),
        )

        return cursor.lastrowid


def test_hardening_creates_daily_report_immutability_triggers(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    names = (
        integrity_module
        .get_integrity_trigger_names()
    )

    assert names.count(
        "trg_daily_reports_immutable_update"
    ) == 1

    assert names.count(
        "trg_daily_reports_immutable_delete"
    ) == 1


def test_daily_report_hardening_is_idempotent(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()
    integrity_module.apply_database_integrity_hardening()

    names = (
        integrity_module
        .get_integrity_trigger_names()
    )

    assert names.count(
        "trg_daily_reports_immutable_update"
    ) == 1

    assert names.count(
        "trg_daily_reports_immutable_delete"
    ) == 1


def test_new_daily_report_insert_remains_allowed(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    report_id = insert_daily_report(
        integrity_database
    )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT *
            FROM daily_reports
            WHERE id = ?;
            """,
            (report_id,),
        ).fetchone()

    assert stored is not None
    assert stored["business_date"] == "2026-11-04"
    assert stored["health_status"] == "attention"


def test_multiple_reports_for_same_business_date_remain_allowed(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    first_id = insert_daily_report(
        integrity_database,
        generated_at_utc=(
            "2026-11-04T14:00:00+00:00"
        ),
    )

    second_id = insert_daily_report(
        integrity_database,
        generated_at_utc=(
            "2026-11-04T15:00:00+00:00"
        ),
        health_status="healthy",
    )

    assert first_id != second_id

    with integrity_database() as connection:
        count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM daily_reports
            WHERE business_date = '2026-11-04';
            """
        ).fetchone()["count"]

    assert count == 2


def test_raw_update_of_daily_report_is_rejected(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    report_id = insert_daily_report(
        integrity_database
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="historical daily reports are immutable",
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE daily_reports
                SET health_status = 'healthy'
                WHERE id = ?;
                """,
                (report_id,),
            )


def test_failed_update_leaves_daily_report_unchanged(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    report_id = insert_daily_report(
        integrity_database
    )

    with integrity_database() as connection:
        original = connection.execute(
            """
            SELECT
                health_status,
                report_json,
                generated_at_utc
            FROM daily_reports
            WHERE id = ?;
            """,
            (report_id,),
        ).fetchone()

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE daily_reports
                SET
                    health_status = 'healthy',
                    report_json = '{}',
                    generated_at_utc = (
                        '2030-01-01T00:00:00+00:00'
                    )
                WHERE id = ?;
                """,
                (report_id,),
            )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT
                health_status,
                report_json,
                generated_at_utc
            FROM daily_reports
            WHERE id = ?;
            """,
            (report_id,),
        ).fetchone()

    assert stored["health_status"] == (
        original["health_status"]
    )

    assert stored["report_json"] == (
        original["report_json"]
    )

    assert stored["generated_at_utc"] == (
        original["generated_at_utc"]
    )


def test_raw_delete_of_daily_report_is_rejected(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    report_id = insert_daily_report(
        integrity_database
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="historical daily reports are immutable",
    ):
        with integrity_database() as connection:
            connection.execute(
                """
                DELETE FROM daily_reports
                WHERE id = ?;
                """,
                (report_id,),
            )


def test_failed_delete_preserves_daily_report(
    integrity_database,
):
    integrity_module.apply_database_integrity_hardening()

    report_id = insert_daily_report(
        integrity_database
    )

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                DELETE FROM daily_reports
                WHERE id = ?;
                """,
                (report_id,),
            )

    with integrity_database() as connection:
        stored = connection.execute(
            """
            SELECT id
            FROM daily_reports
            WHERE id = ?;
            """,
            (report_id,),
        ).fetchone()

    assert stored is not None


def test_existing_daily_report_becomes_protected_after_hardening(
    integrity_database,
):
    report_id = insert_daily_report(
        integrity_database
    )

    integrity_module.apply_database_integrity_hardening()

    with pytest.raises(sqlite3.IntegrityError):
        with integrity_database() as connection:
            connection.execute(
                """
                UPDATE daily_reports
                SET report_timezone = 'UTC'
                WHERE id = ?;
                """,
                (report_id,),
            )
