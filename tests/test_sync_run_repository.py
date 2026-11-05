import sqlite3
from contextlib import contextmanager

import pytest

import repositories.sync_run_repository as repository_module
from repositories.sync_run_repository import (
    SyncRunRepository,
    SyncRunStateError,
)


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
def sync_run_repository(
    tmp_path,
    monkeypatch,
):
    database_path = (
        tmp_path
        / "sync_runs_test.db"
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
        repository_module,
        "get_db_connection",
        temporary_db_connection,
    )

    return SyncRunRepository()


def test_start_run_creates_running_audit_record(
    sync_run_repository,
):
    run_id = sync_run_repository.start_run()

    stored = (
        sync_run_repository.get_run_by_id(
            run_id
        )
    )

    assert run_id == 1
    assert stored["status"] == "running"
    assert stored["started_at"] is not None
    assert stored["completed_at"] is None
    assert stored["products_seen"] == 0
    assert stored["variants_seen"] == 0
    assert stored["error_message"] is None


def test_mark_success_records_terminal_success(
    sync_run_repository,
):
    run_id = sync_run_repository.start_run()

    sync_run_repository.mark_success(
        run_id=run_id,
        products_seen=3,
        variants_seen=4,
    )

    stored = (
        sync_run_repository.get_run_by_id(
            run_id
        )
    )

    assert stored["status"] == "success"
    assert stored["completed_at"] is not None
    assert stored["products_seen"] == 3
    assert stored["variants_seen"] == 4
    assert stored["error_message"] is None


def test_mark_failed_records_terminal_failure(
    sync_run_repository,
):
    run_id = sync_run_repository.start_run()

    sync_run_repository.mark_failed(
        run_id=run_id,
        error_message=(
            "RuntimeError: simulated failure"
        ),
    )

    stored = (
        sync_run_repository.get_run_by_id(
            run_id
        )
    )

    assert stored["status"] == "failed"
    assert stored["completed_at"] is not None

    assert (
        stored["error_message"]
        == "RuntimeError: simulated failure"
    )


def test_success_run_cannot_transition_to_failed(
    sync_run_repository,
):
    run_id = sync_run_repository.start_run()

    sync_run_repository.mark_success(
        run_id=run_id,
        products_seen=3,
        variants_seen=4,
    )

    with pytest.raises(
        SyncRunStateError,
        match="cannot transition from 'success' to 'failed'",
    ):
        sync_run_repository.mark_failed(
            run_id=run_id,
            error_message="late failure",
        )


def test_failed_run_cannot_transition_to_success(
    sync_run_repository,
):
    run_id = sync_run_repository.start_run()

    sync_run_repository.mark_failed(
        run_id=run_id,
        error_message="sync failed",
    )

    with pytest.raises(
        SyncRunStateError,
        match="cannot transition from 'failed' to 'success'",
    ):
        sync_run_repository.mark_success(
            run_id=run_id,
            products_seen=3,
            variants_seen=4,
        )


def test_success_run_cannot_be_completed_twice(
    sync_run_repository,
):
    run_id = sync_run_repository.start_run()

    sync_run_repository.mark_success(
        run_id=run_id,
        products_seen=3,
        variants_seen=4,
    )

    with pytest.raises(
        SyncRunStateError,
        match="cannot transition from 'success' to 'success'",
    ):
        sync_run_repository.mark_success(
            run_id=run_id,
            products_seen=99,
            variants_seen=99,
        )

    stored = (
        sync_run_repository.get_run_by_id(
            run_id
        )
    )

    assert stored["products_seen"] == 3
    assert stored["variants_seen"] == 4


def test_missing_run_cannot_be_marked_success(
    sync_run_repository,
):
    with pytest.raises(
        ValueError,
        match="Synchronization run 999 does not exist",
    ):
        sync_run_repository.mark_success(
            run_id=999,
            products_seen=3,
            variants_seen=4,
        )


def test_missing_run_cannot_be_marked_failed(
    sync_run_repository,
):
    with pytest.raises(
        ValueError,
        match="Synchronization run 999 does not exist",
    ):
        sync_run_repository.mark_failed(
            run_id=999,
            error_message="failure",
        )


@pytest.mark.parametrize(
    "field_name, products_seen, variants_seen",
    [
        ("products_seen", -1, 4),
        ("variants_seen", 3, -1),
    ],
)
def test_success_counts_cannot_be_negative(
    sync_run_repository,
    field_name,
    products_seen,
    variants_seen,
):
    run_id = sync_run_repository.start_run()

    with pytest.raises(
        ValueError,
        match=f"{field_name} cannot be negative",
    ):
        sync_run_repository.mark_success(
            run_id=run_id,
            products_seen=products_seen,
            variants_seen=variants_seen,
        )


@pytest.mark.parametrize(
    "invalid_value",
    [
        True,
        "3",
        3.5,
    ],
)
def test_success_counts_must_be_integers(
    sync_run_repository,
    invalid_value,
):
    run_id = sync_run_repository.start_run()

    with pytest.raises(
        ValueError,
        match="products_seen must be an integer",
    ):
        sync_run_repository.mark_success(
            run_id=run_id,
            products_seen=invalid_value,
            variants_seen=4,
        )


def test_failure_message_is_trimmed_and_capped(
    sync_run_repository,
):
    run_id = sync_run_repository.start_run()

    sync_run_repository.mark_failed(
        run_id=run_id,
        error_message=(
            "  "
            + ("X" * 1500)
            + "  "
        ),
    )

    stored = (
        sync_run_repository.get_run_by_id(
            run_id
        )
    )

    assert len(
        stored["error_message"]
    ) == 1000

    assert stored["error_message"] == (
        "X" * 1000
    )


@pytest.mark.parametrize(
    "invalid_message",
    [
        "",
        "   ",
        None,
        123,
    ],
)
def test_failure_message_must_be_non_empty_string(
    sync_run_repository,
    invalid_message,
):
    run_id = sync_run_repository.start_run()

    with pytest.raises(ValueError):
        sync_run_repository.mark_failed(
            run_id=run_id,
            error_message=invalid_message,
        )


@pytest.mark.parametrize(
    "invalid_run_id",
    [
        0,
        -1,
        True,
        "1",
    ],
)
def test_run_id_must_be_positive_integer(
    sync_run_repository,
    invalid_run_id,
):
    with pytest.raises(
        ValueError,
        match="run_id must be a positive integer",
    ):
        sync_run_repository.get_run_by_id(
            invalid_run_id
        )


def test_recent_history_preserves_terminal_states(
    sync_run_repository,
):
    success_id = (
        sync_run_repository.start_run()
    )

    sync_run_repository.mark_success(
        run_id=success_id,
        products_seen=3,
        variants_seen=4,
    )

    failed_id = (
        sync_run_repository.start_run()
    )

    sync_run_repository.mark_failed(
        run_id=failed_id,
        error_message="test failure",
    )

    recent = (
        sync_run_repository.get_recent_runs(
            limit=5
        )
    )

    assert recent[0]["id"] == failed_id
    assert recent[0]["status"] == "failed"

    assert recent[1]["id"] == success_id
    assert recent[1]["status"] == "success"


def test_zero_recent_limit_returns_empty_list(
    sync_run_repository,
):
    sync_run_repository.start_run()

    assert (
        sync_run_repository.get_recent_runs(
            limit=0
        )
        == []
    )


@pytest.mark.parametrize(
    "invalid_limit",
    [
        -1,
        True,
        "5",
    ],
)
def test_recent_limit_is_validated(
    sync_run_repository,
    invalid_limit,
):
    with pytest.raises(ValueError):
        sync_run_repository.get_recent_runs(
            limit=invalid_limit
        )
