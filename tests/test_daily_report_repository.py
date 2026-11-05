import sqlite3
from contextlib import contextmanager

import pytest

import repositories.daily_report_repository as repository_module
from repositories.daily_report_repository import (
    DailyReportRepository,
)


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
def daily_report_repository(
    tmp_path,
    monkeypatch,
):
    """
    Return a DailyReportRepository connected to a
    temporary SQLite database created only for this test.

    The real data/shopify.db file is never touched.
    """

    database_path = (
        tmp_path
        / "daily_reports_test.db"
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
        repository_module,
        "get_db_connection",
        temporary_db_connection,
    )

    return DailyReportRepository()


@pytest.fixture
def sample_report():
    """
    Minimal but realistic structured report.
    """

    return {
        "generated_at_utc":
            "2026-11-03T21:00:00+00:00",

        "report_context": {
            "timezone":
                "America/Bogota",

            "local_date":
                "2026-11-03",
        },

        "store": {
            "products_monitored": 3,
            "variants_monitored": 4,
        },

        "profitability": {
            "merchandise_revenue": "50.00",
            "product_cost": "21.50",
            "estimated_gross_profit": "28.50",
            "gross_margin_percent": "57.00",
        },

        "inventory": {
            "low_inventory_variants": 2,
            "out_of_stock_variants": 0,
        },

        "health": {
            "status": "attention",
            "headline": (
                "The store is operating, "
                "but some items require attention."
            ),
        },
    }


def test_save_report_returns_new_id_and_increments_count(
    daily_report_repository,
    sample_report,
):
    report_id = (
        daily_report_repository
        .save_report(
            sample_report
        )
    )

    assert report_id == 1

    assert (
        daily_report_repository
        .count_reports()
        == 1
    )


def test_saved_report_round_trip_preserves_full_structure(
    daily_report_repository,
    sample_report,
):
    report_id = (
        daily_report_repository
        .save_report(
            sample_report
        )
    )

    stored = (
        daily_report_repository
        .get_report_by_id(
            report_id
        )
    )

    assert stored is not None

    assert stored["id"] == report_id
    assert stored["business_date"] == "2026-11-03"
    assert stored["report_timezone"] == "America/Bogota"

    assert (
        stored["generated_at_utc"]
        == "2026-11-03T21:00:00+00:00"
    )

    assert stored["health_status"] == "attention"

    assert stored["report"] == sample_report


def test_get_latest_report_returns_none_when_empty(
    daily_report_repository,
):
    assert (
        daily_report_repository
        .get_latest_report()
        is None
    )


def test_get_latest_report_returns_newest_generated_report(
    daily_report_repository,
    sample_report,
):
    older_report = {
        **sample_report,
        "generated_at_utc":
            "2026-11-03T20:00:00+00:00",
    }

    newer_report = {
        **sample_report,
        "generated_at_utc":
            "2026-11-03T22:00:00+00:00",
    }

    older_id = (
        daily_report_repository
        .save_report(
            older_report
        )
    )

    newer_id = (
        daily_report_repository
        .save_report(
            newer_report
        )
    )

    latest = (
        daily_report_repository
        .get_latest_report()
    )

    assert older_id == 1
    assert newer_id == 2

    assert latest["id"] == newer_id

    assert (
        latest["generated_at_utc"]
        == "2026-11-03T22:00:00+00:00"
    )


def test_get_reports_for_date_filters_and_orders_newest_first(
    daily_report_repository,
    sample_report,
):
    first_report = {
        **sample_report,
        "generated_at_utc":
            "2026-11-03T20:00:00+00:00",
    }

    second_report = {
        **sample_report,
        "generated_at_utc":
            "2026-11-03T22:00:00+00:00",
    }

    other_date_report = {
        **sample_report,
        "generated_at_utc":
            "2026-11-04T15:00:00+00:00",

        "report_context": {
            "timezone":
                "America/Bogota",

            "local_date":
                "2026-11-04",
        },
    }

    first_id = (
        daily_report_repository
        .save_report(
            first_report
        )
    )

    second_id = (
        daily_report_repository
        .save_report(
            second_report
        )
    )

    daily_report_repository.save_report(
        other_date_report
    )

    reports = (
        daily_report_repository
        .get_reports_for_date(
            "2026-11-03"
        )
    )

    assert len(reports) == 2

    assert [
        report["id"]
        for report in reports
    ] == [
        second_id,
        first_id,
    ]


def test_get_recent_reports_respects_limit_and_order(
    daily_report_repository,
    sample_report,
):
    report_ids = []

    for hour in (
        18,
        19,
        20,
        21,
    ):
        report = {
            **sample_report,
            "generated_at_utc": (
                f"2026-11-03T{hour}:00:00+00:00"
            ),
        }

        report_ids.append(
            daily_report_repository
            .save_report(
                report
            )
        )

    recent = (
        daily_report_repository
        .get_recent_reports(
            limit=2
        )
    )

    assert [
        report["id"]
        for report in recent
    ] == [
        report_ids[-1],
        report_ids[-2],
    ]


def test_same_business_date_creates_distinct_immutable_snapshots(
    daily_report_repository,
    sample_report,
):
    first_id = (
        daily_report_repository
        .save_report(
            sample_report
        )
    )

    changed_report = {
        **sample_report,

        "generated_at_utc":
            "2026-11-03T22:00:00+00:00",

        "health": {
            "status": "healthy",
            "headline": "All monitored checks are healthy.",
        },
    }

    second_id = (
        daily_report_repository
        .save_report(
            changed_report
        )
    )

    first_stored = (
        daily_report_repository
        .get_report_by_id(
            first_id
        )
    )

    second_stored = (
        daily_report_repository
        .get_report_by_id(
            second_id
        )
    )

    assert first_id != second_id

    assert (
        daily_report_repository
        .count_reports()
        == 2
    )

    assert (
        first_stored["health_status"]
        == "attention"
    )

    assert (
        first_stored["report"]["health"]["status"]
        == "attention"
    )

    assert (
        second_stored["health_status"]
        == "healthy"
    )


def test_get_report_by_id_returns_none_for_missing_report(
    daily_report_repository,
):
    assert (
        daily_report_repository
        .get_report_by_id(
            999
        )
        is None
    )


def test_save_report_rejects_non_dictionary(
    daily_report_repository,
):
    with pytest.raises(
        ValueError,
        match="report must be a dictionary",
    ):
        daily_report_repository.save_report(
            "not-a-dictionary"
        )


def test_save_report_requires_report_context(
    daily_report_repository,
    sample_report,
):
    invalid_report = {
        key: value
        for key, value
        in sample_report.items()
        if key != "report_context"
    }

    with pytest.raises(
        ValueError,
        match=(
            "report must contain a "
            "report_context dictionary"
        ),
    ):
        daily_report_repository.save_report(
            invalid_report
        )


def test_save_report_requires_health_dictionary(
    daily_report_repository,
    sample_report,
):
    invalid_report = {
        key: value
        for key, value
        in sample_report.items()
        if key != "health"
    }

    with pytest.raises(
        ValueError,
        match=(
            "report must contain a "
            "health dictionary"
        ),
    ):
        daily_report_repository.save_report(
            invalid_report
        )


def test_save_report_rejects_invalid_business_date(
    daily_report_repository,
    sample_report,
):
    invalid_report = {
        **sample_report,

        "report_context": {
            "timezone":
                "America/Bogota",

            "local_date":
                "not-a-date",
        },
    }

    with pytest.raises(
        ValueError,
        match=(
            "business_date must use "
            "YYYY-MM-DD format"
        ),
    ):
        daily_report_repository.save_report(
            invalid_report
        )


def test_save_report_requires_timezone(
    daily_report_repository,
    sample_report,
):
    invalid_report = {
        **sample_report,

        "report_context": {
            "timezone":
                "   ",

            "local_date":
                "2026-11-03",
        },
    }

    with pytest.raises(
        ValueError,
        match="report timezone is required",
    ):
        daily_report_repository.save_report(
            invalid_report
        )


def test_save_report_rejects_naive_generated_timestamp(
    daily_report_repository,
    sample_report,
):
    invalid_report = {
        **sample_report,
        "generated_at_utc":
            "2026-11-03T21:00:00",
    }

    with pytest.raises(
        ValueError,
        match=(
            "generated_at_utc must include "
            "timezone information"
        ),
    ):
        daily_report_repository.save_report(
            invalid_report
        )


@pytest.mark.parametrize(
    "invalid_status",
    [
        "",
        "warning",
        "success",
        "unknown",
    ],
)
def test_save_report_rejects_invalid_health_status(
    daily_report_repository,
    sample_report,
    invalid_status,
):
    invalid_report = {
        **sample_report,

        "health": {
            "status": invalid_status,
            "headline": "Test",
        },
    }

    with pytest.raises(
        ValueError,
        match=(
            "health status must be one of: "
            "healthy, attention, critical"
        ),
    ):
        daily_report_repository.save_report(
            invalid_report
        )


def test_save_report_rejects_non_json_serializable_data(
    daily_report_repository,
    sample_report,
):
    invalid_report = {
        **sample_report,
        "not_json_serializable": {
            "value",
        },
    }

    with pytest.raises(
        ValueError,
        match=(
            "report contains data that "
            "cannot be serialized to JSON"
        ),
    ):
        daily_report_repository.save_report(
            invalid_report
        )


@pytest.mark.parametrize(
    "invalid_report_id",
    [
        0,
        -1,
        True,
        "1",
    ],
)
def test_get_report_by_id_requires_positive_integer(
    daily_report_repository,
    invalid_report_id,
):
    with pytest.raises(
        ValueError,
        match=(
            "report_id must be a "
            "positive integer"
        ),
    ):
        daily_report_repository.get_report_by_id(
            invalid_report_id
        )


@pytest.mark.parametrize(
    "invalid_limit",
    [
        0,
        -1,
        True,
        "5",
    ],
)
def test_get_recent_reports_requires_positive_integer_limit(
    daily_report_repository,
    invalid_limit,
):
    with pytest.raises(
        ValueError,
        match=(
            "limit must be a "
            "positive integer"
        ),
    ):
        daily_report_repository.get_recent_reports(
            limit=invalid_limit
        )


def test_get_reports_for_date_validates_date_format(
    daily_report_repository,
):
    with pytest.raises(
        ValueError,
        match=(
            "business_date must use "
            "YYYY-MM-DD format"
        ),
    ):
        daily_report_repository.get_reports_for_date(
            "11/03/2026"
        )
