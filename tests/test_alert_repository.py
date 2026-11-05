import sqlite3
from contextlib import contextmanager

import pytest

import repositories.alert_repository as repository_module
from repositories.alert_repository import AlertRepository


CREATE_ALERTS_SCHEMA_SQL = """
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

CREATE INDEX idx_alerts_status
ON alerts(status);

CREATE INDEX idx_alerts_type
ON alerts(alert_type);

CREATE INDEX idx_alerts_created_at
ON alerts(created_at);

CREATE INDEX idx_alerts_entity
ON alerts(entity_type, entity_id);

CREATE UNIQUE INDEX idx_alerts_open_dedupe
ON alerts(dedupe_key)
WHERE status = 'open';
"""


@pytest.fixture
def alert_repository(
    tmp_path,
    monkeypatch,
):
    """
    Return an AlertRepository connected to a temporary
    SQLite database.

    The production data/shopify.db file is never touched.
    """

    database_path = (
        tmp_path
        / "alerts_test.db"
    )

    connection = sqlite3.connect(
        database_path
    )

    try:
        connection.executescript(
            CREATE_ALERTS_SCHEMA_SQL
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

    return AlertRepository()


def create_standard_alert(
    alert_repository,
    *,
    dedupe_key="low_inventory:variant-001",
):
    return alert_repository.create_or_touch_alert(
        alert_type="low_inventory",
        severity="warning",
        dedupe_key=dedupe_key,
        title="Low inventory for AUTO-CAP-001",
        message="AUTO-CAP-001 has 2 units in stock.",
        entity_type="variant",
        entity_id="variant-001",
    )


def test_create_alert_creates_open_history_row(
    alert_repository,
):
    alert = create_standard_alert(
        alert_repository
    )

    assert alert["id"] == 1
    assert alert["alert_type"] == "low_inventory"
    assert alert["severity"] == "warning"
    assert alert["status"] == "open"

    assert (
        alert["dedupe_key"]
        == "low_inventory:variant-001"
    )

    assert alert["occurrence_count"] == 1
    assert alert["resolved_at"] is None

    assert (
        alert_repository.count_all_alerts()
        == 1
    )

    assert (
        alert_repository.count_open_alerts()
        == 1
    )


def test_alert_fields_are_normalized(
    alert_repository,
):
    alert = (
        alert_repository
        .create_or_touch_alert(
            alert_type="  LOW_INVENTORY  ",
            severity="  WARNING  ",
            dedupe_key="  test:key  ",
            title="  Test title  ",
            message="  Test message  ",
            entity_type="variant",
            entity_id="variant-001",
        )
    )

    assert alert["alert_type"] == "low_inventory"
    assert alert["severity"] == "warning"
    assert alert["dedupe_key"] == "test:key"
    assert alert["title"] == "Test title"
    assert alert["message"] == "Test message"


def test_touching_open_alert_reuses_same_row(
    alert_repository,
):
    first = create_standard_alert(
        alert_repository
    )

    second = create_standard_alert(
        alert_repository
    )

    assert first["id"] == second["id"]
    assert second["occurrence_count"] == 2

    assert (
        alert_repository.count_all_alerts()
        == 1
    )

    assert (
        alert_repository.count_open_alerts()
        == 1
    )


def test_touching_alert_updates_current_details(
    alert_repository,
):
    first = create_standard_alert(
        alert_repository
    )

    second = (
        alert_repository
        .create_or_touch_alert(
            alert_type="low_inventory",
            severity="critical",
            dedupe_key=first["dedupe_key"],
            title="Out of stock",
            message="Inventory is now zero.",
            entity_type="variant",
            entity_id="variant-001",
        )
    )

    assert second["id"] == first["id"]
    assert second["occurrence_count"] == 2
    assert second["severity"] == "critical"
    assert second["title"] == "Out of stock"

    assert (
        second["message"]
        == "Inventory is now zero."
    )


def test_resolve_alert_closes_open_alert(
    alert_repository,
):
    alert = create_standard_alert(
        alert_repository
    )

    resolved = (
        alert_repository.resolve_alert(
            alert["dedupe_key"]
        )
    )

    stored = (
        alert_repository.get_alert_by_id(
            alert["id"]
        )
    )

    assert resolved is True
    assert stored["status"] == "resolved"
    assert stored["resolved_at"] is not None

    assert (
        alert_repository.count_open_alerts()
        == 0
    )

    assert (
        alert_repository.count_all_alerts()
        == 1
    )


def test_resolve_nonexistent_alert_returns_false(
    alert_repository,
):
    assert (
        alert_repository.resolve_alert(
            "does-not-exist"
        )
        is False
    )


def test_resolve_alert_rejects_blank_dedupe_key(
    alert_repository,
):
    with pytest.raises(
        ValueError,
        match="dedupe_key is required",
    ):
        alert_repository.resolve_alert(
            "   "
        )


def test_resolved_alert_is_not_returned_as_open(
    alert_repository,
):
    alert = create_standard_alert(
        alert_repository
    )

    alert_repository.resolve_alert(
        alert["dedupe_key"]
    )

    assert (
        alert_repository
        .get_open_alert_by_dedupe_key(
            alert["dedupe_key"]
        )
        is None
    )

    assert (
        alert_repository.get_open_alerts()
        == []
    )


def test_resolved_condition_can_create_new_history_row(
    alert_repository,
):
    first = create_standard_alert(
        alert_repository
    )

    alert_repository.resolve_alert(
        first["dedupe_key"]
    )

    second = create_standard_alert(
        alert_repository
    )

    assert second["id"] != first["id"]
    assert second["status"] == "open"
    assert second["occurrence_count"] == 1

    assert (
        alert_repository.count_all_alerts()
        == 2
    )

    assert (
        alert_repository.count_open_alerts()
        == 1
    )

    old_alert = (
        alert_repository.get_alert_by_id(
            first["id"]
        )
    )

    assert old_alert["status"] == "resolved"


def test_get_alert_by_id_returns_none_when_missing(
    alert_repository,
):
    assert (
        alert_repository.get_alert_by_id(
            999
        )
        is None
    )


def test_get_open_alert_by_dedupe_key_returns_open_alert(
    alert_repository,
):
    created = create_standard_alert(
        alert_repository
    )

    found = (
        alert_repository
        .get_open_alert_by_dedupe_key(
            created["dedupe_key"]
        )
    )

    assert found is not None
    assert found["id"] == created["id"]


def test_get_open_alerts_returns_only_open_rows(
    alert_repository,
):
    first = create_standard_alert(
        alert_repository,
        dedupe_key="alert:first",
    )

    second = create_standard_alert(
        alert_repository,
        dedupe_key="alert:second",
    )

    alert_repository.resolve_alert(
        first["dedupe_key"]
    )

    open_alerts = (
        alert_repository.get_open_alerts()
    )

    assert len(open_alerts) == 1
    assert open_alerts[0]["id"] == second["id"]


def test_get_open_alerts_preserves_creation_order(
    alert_repository,
):
    first = create_standard_alert(
        alert_repository,
        dedupe_key="alert:first",
    )

    second = create_standard_alert(
        alert_repository,
        dedupe_key="alert:second",
    )

    third = create_standard_alert(
        alert_repository,
        dedupe_key="alert:third",
    )

    assert [
        alert["id"]
        for alert in (
            alert_repository
            .get_open_alerts()
        )
    ] == [
        first["id"],
        second["id"],
        third["id"],
    ]


def test_get_recent_alerts_returns_newest_first(
    alert_repository,
):
    first = create_standard_alert(
        alert_repository,
        dedupe_key="alert:first",
    )

    second = create_standard_alert(
        alert_repository,
        dedupe_key="alert:second",
    )

    third = create_standard_alert(
        alert_repository,
        dedupe_key="alert:third",
    )

    recent = (
        alert_repository.get_recent_alerts(
            limit=3
        )
    )

    assert [
        alert["id"]
        for alert in recent
    ] == [
        third["id"],
        second["id"],
        first["id"],
    ]


def test_recent_alert_history_includes_resolved_rows(
    alert_repository,
):
    alert = create_standard_alert(
        alert_repository
    )

    alert_repository.resolve_alert(
        alert["dedupe_key"]
    )

    recent = (
        alert_repository.get_recent_alerts(
            limit=5
        )
    )

    assert len(recent) == 1
    assert recent[0]["status"] == "resolved"


def test_get_recent_alerts_respects_limit(
    alert_repository,
):
    for index in range(5):
        create_standard_alert(
            alert_repository,
            dedupe_key=f"alert:{index}",
        )

    recent = (
        alert_repository.get_recent_alerts(
            limit=2
        )
    )

    assert len(recent) == 2


def test_count_methods_track_history_and_open_state(
    alert_repository,
):
    first = create_standard_alert(
        alert_repository,
        dedupe_key="alert:first",
    )

    create_standard_alert(
        alert_repository,
        dedupe_key="alert:second",
    )

    alert_repository.resolve_alert(
        first["dedupe_key"]
    )

    assert (
        alert_repository.count_all_alerts()
        == 2
    )

    assert (
        alert_repository.count_open_alerts()
        == 1
    )


@pytest.mark.parametrize(
    "invalid_type",
    [
        "inventory",
        "unknown",
    ],
)
def test_unsupported_alert_type_is_rejected(
    alert_repository,
    invalid_type,
):
    with pytest.raises(
        ValueError,
        match="Unsupported alert_type",
    ):
        alert_repository.create_or_touch_alert(
            alert_type=invalid_type,
            severity="warning",
            dedupe_key="test:key",
            title="Test",
            message="Test message",
        )


@pytest.mark.parametrize(
    "invalid_severity",
    [
        "notice",
        "fatal",
    ],
)
def test_unsupported_severity_is_rejected(
    alert_repository,
    invalid_severity,
):
    with pytest.raises(
        ValueError,
        match="Unsupported severity",
    ):
        alert_repository.create_or_touch_alert(
            alert_type="low_inventory",
            severity=invalid_severity,
            dedupe_key="test:key",
            title="Test",
            message="Test message",
        )


@pytest.mark.parametrize(
    (
        "dedupe_key",
        "title",
        "message",
        "expected_message",
    ),
    [
        (
            "",
            "Title",
            "Message",
            "dedupe_key is required",
        ),
        (
            "test:key",
            "",
            "Message",
            "title is required",
        ),
        (
            "test:key",
            "Title",
            "",
            "message is required",
        ),
    ],
)
def test_required_alert_text_fields_are_validated(
    alert_repository,
    dedupe_key,
    title,
    message,
    expected_message,
):
    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        alert_repository.create_or_touch_alert(
            alert_type="low_inventory",
            severity="warning",
            dedupe_key=dedupe_key,
            title=title,
            message=message,
        )


@pytest.mark.parametrize(
    "invalid_limit",
    [
        0,
        -1,
    ],
)
def test_recent_alert_limit_must_be_positive(
    alert_repository,
    invalid_limit,
):
    with pytest.raises(
        ValueError,
        match="limit must be greater than zero",
    ):
        alert_repository.get_recent_alerts(
            limit=invalid_limit
        )


def test_all_supported_alert_types_can_be_persisted(
    alert_repository,
):
    alert_types = [
        ("new_order", "info"),
        ("missing_cost", "warning"),
        ("low_inventory", "warning"),
        ("sync_failure", "error"),
    ]

    for index, (
        alert_type,
        severity,
    ) in enumerate(
        alert_types,
        start=1,
    ):
        alert_repository.create_or_touch_alert(
            alert_type=alert_type,
            severity=severity,
            dedupe_key=f"{alert_type}:{index}",
            title=f"{alert_type} test",
            message="Test message",
        )

    assert (
        alert_repository.count_all_alerts()
        == 4
    )
