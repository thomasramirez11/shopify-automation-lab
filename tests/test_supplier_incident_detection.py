import json
import sqlite3
from contextlib import contextmanager

import pytest

from database.supplier_incident_schema import (
    ensure_supplier_incident_schema,
)
from supplier.orchestration.health_models import (
    ControlPlaneHealthReport,
    ControlPlaneHealthStatus,
    HealthReason,
    SLOCheck,
)
from supplier.orchestration.health_policy import (
    DEFAULT_CONTROL_PLANE_SLO_POLICY,
)
from supplier.orchestration.incident_models import (
    HealthTransitionType,
    IncidentAction,
)
from supplier.orchestration.incident_policy import (
    build_health_fingerprint,
    build_incident_id,
    classify_health_transition,
)
from supplier.orchestration.incident_repository import (
    SupplierIncidentRepository,
)
from supplier.orchestration.incident_service import (
    SupplierIncidentMonitoringService,
)


SUPPLIER = "demo_supplier"


def factory():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    @contextmanager
    def connection_factory():
        try:
            yield connection
        finally:
            connection.commit()

    return (
        connection,
        connection_factory,
    )


def repository(
    connection_factory,
):
    return SupplierIncidentRepository(
        connection_factory=(
            connection_factory
        )
    )


def service(
    connection_factory,
):
    repo = repository(
        connection_factory
    )

    return (
        repo,
        SupplierIncidentMonitoringService(
            repo
        ),
    )


def report(
    status=ControlPlaneHealthStatus.HEALTHY,
    *,
    score=None,
    policy_fingerprint="a" * 64,
    human_cases=0,
    retries=0,
):
    if score is None:
        score = {
            ControlPlaneHealthStatus.HEALTHY:
                100,
            ControlPlaneHealthStatus.DEGRADED:
                70,
            ControlPlaneHealthStatus.CRITICAL:
                25,
        }[status]

    healthy = (
        status
        == ControlPlaneHealthStatus.HEALTHY
    )

    checks = (
        SLOCheck(
            name="history_depth",
            met=True,
            observed="4",
            target=">=2",
        ),
        SLOCheck(
            name="healthy_run_percentage",
            met=healthy,
            observed=(
                "100.0%"
                if healthy
                else "50.0%"
            ),
            target=">=75.0%",
        ),
    )

    reasons = (
        (
            HealthReason.ALL_SLOS_MET,
        )
        if healthy
        else (
            HealthReason
            .HEALTHY_RUN_RATIO_BELOW_TARGET,
        )
    )

    return ControlPlaneHealthReport(
        supplier_code=SUPPLIER,
        status=status,
        score=score,
        history_runs_evaluated=4,
        healthy_runs=(
            4
            if healthy
            else 2
        ),
        healthy_run_percentage=(
            100.0
            if healthy
            else 50.0
        ),
        consecutive_healthy_runs=(
            4
            if healthy
            else 0
        ),
        unresolved_human_cases=(
            human_cases
        ),
        queued_retry_attempts=(
            retries
        ),
        slo_checks=checks,
        reasons=reasons,
        slo_policy_fingerprint=(
            policy_fingerprint
        ),
    )


def record_sequence(
    connection_factory,
    statuses,
):
    repo, svc = service(
        connection_factory
    )

    results = [
        svc.record_health(
            report(status)
        )
        for status in statuses
    ]

    return (
        repo,
        svc,
        results,
    )


# 1
def test_schema_creates_health_table():
    connection, _ = factory()

    ensure_supplier_incident_schema(
        connection
    )

    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'supplier_health_events';
        """
    ).fetchone()

    assert row is not None


# 2
def test_schema_creates_incident_table():
    connection, _ = factory()

    ensure_supplier_incident_schema(
        connection
    )

    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'supplier_incident_events';
        """
    ).fetchone()

    assert row is not None


# 3
def test_schema_is_idempotent():
    connection, _ = factory()

    ensure_supplier_incident_schema(
        connection
    )
    ensure_supplier_incident_schema(
        connection
    )


# 4
def test_health_ledger_update_is_blocked():
    connection, connection_factory = factory()

    _, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.HEALTHY
        ],
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            UPDATE supplier_health_events
            SET health_score = 1;
            """
        )


# 5
def test_health_ledger_delete_is_blocked():
    connection, connection_factory = factory()

    record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.HEALTHY
        ],
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            DELETE FROM supplier_health_events;
            """
        )


# 6
def test_incident_ledger_update_is_blocked():
    connection, connection_factory = factory()

    record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED
        ],
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            UPDATE supplier_incident_events
            SET health_score = 1;
            """
        )


# 7
def test_incident_ledger_delete_is_blocked():
    connection, connection_factory = factory()

    record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED
        ],
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            DELETE FROM supplier_incident_events;
            """
        )


# 8
def test_health_fingerprint_is_deterministic():
    current = report()

    assert (
        build_health_fingerprint(
            current
        )
        == build_health_fingerprint(
            current
        )
    )


# 9
def test_health_fingerprint_changes_with_status():
    assert (
        build_health_fingerprint(
            report(
                ControlPlaneHealthStatus.HEALTHY
            )
        )
        != build_health_fingerprint(
            report(
                ControlPlaneHealthStatus.DEGRADED
            )
        )
    )


# 10
def test_incident_id_is_deterministic():
    first = build_incident_id(
        supplier_code=SUPPLIER,
        opening_health_event_id=1,
    )

    second = build_incident_id(
        supplier_code=SUPPLIER,
        opening_health_event_id=1,
    )

    assert first == second


# 11
def test_incident_id_changes_for_new_opening_event():
    assert (
        build_incident_id(
            supplier_code=SUPPLIER,
            opening_health_event_id=1,
        )
        != build_incident_id(
            supplier_code=SUPPLIER,
            opening_health_event_id=2,
        )
    )


# 12
def test_initial_healthy_observation_opens_no_incident():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.HEALTHY
        ],
    )

    result = results[0]

    assert (
        result.health_transition
        == HealthTransitionType.INITIAL
    )
    assert (
        result.incident_action
        == IncidentAction.NONE
    )
    assert repo.count_incidents(
        SUPPLIER
    ) == 0


# 13
def test_second_healthy_observation_is_unchanged():
    _, connection_factory = factory()

    _, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.HEALTHY,
            ControlPlaneHealthStatus.HEALTHY,
        ],
    )

    assert (
        results[1].health_transition
        == HealthTransitionType.UNCHANGED
    )
    assert (
        results[1].incident_action
        == IncidentAction.NONE
    )


# 14
def test_initial_degraded_health_opens_incident():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED
        ],
    )

    assert (
        results[0].incident_action
        == IncidentAction.OPENED
    )
    assert repo.count_open_incidents(
        SUPPLIER
    ) == 1


# 15
def test_initial_critical_health_opens_incident():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.CRITICAL
        ],
    )

    assert (
        results[0].incident_action
        == IncidentAction.OPENED
    )
    assert repo.count_incidents(
        SUPPLIER
    ) == 1


# 16
def test_healthy_to_degraded_transition_classified():
    assert (
        classify_health_transition(
            previous_status="healthy",
            current_status="degraded",
        )
        == (
            HealthTransitionType
            .HEALTH_DEGRADED
        )
    )


# 17
def test_healthy_to_critical_transition_classified():
    assert (
        classify_health_transition(
            previous_status="healthy",
            current_status="critical",
        )
        == (
            HealthTransitionType
            .HEALTH_CRITICAL
        )
    )


# 18
def test_degraded_to_critical_escalates_incident():
    _, connection_factory = factory()

    _, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED,
            ControlPlaneHealthStatus.CRITICAL,
        ],
    )

    assert (
        results[1].health_transition
        == HealthTransitionType.HEALTH_ESCALATED
    )
    assert (
        results[1].incident_action
        == IncidentAction.ESCALATED
    )


# 19
def test_critical_to_degraded_deescalates_incident():
    _, connection_factory = factory()

    _, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.CRITICAL,
            ControlPlaneHealthStatus.DEGRADED,
        ],
    )

    assert (
        results[1].health_transition
        == HealthTransitionType.HEALTH_IMPROVED
    )
    assert (
        results[1].incident_action
        == IncidentAction.DEESCALATED
    )


# 20
def test_degraded_to_healthy_closes_incident():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED,
            ControlPlaneHealthStatus.HEALTHY,
        ],
    )

    assert (
        results[1].health_transition
        == HealthTransitionType.HEALTH_RECOVERED
    )
    assert (
        results[1].incident_action
        == IncidentAction.CLOSED
    )
    assert repo.count_open_incidents(
        SUPPLIER
    ) == 0


# 21
def test_critical_to_healthy_closes_incident():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.CRITICAL,
            ControlPlaneHealthStatus.HEALTHY,
        ],
    )

    assert (
        results[1].incident_action
        == IncidentAction.CLOSED
    )
    assert repo.count_open_incidents(
        SUPPLIER
    ) == 0


# 22
def test_repeated_degraded_does_not_duplicate_incident_event():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED,
            ControlPlaneHealthStatus.DEGRADED,
        ],
    )

    incident_id = results[0].incident_id

    assert (
        results[1].incident_action
        == IncidentAction.NONE
    )
    assert len(
        repo.get_incident_events(
            incident_id
        )
    ) == 1


# 23
def test_repeated_critical_does_not_duplicate_escalation():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED,
            ControlPlaneHealthStatus.CRITICAL,
            ControlPlaneHealthStatus.CRITICAL,
        ],
    )

    incident_id = results[0].incident_id

    assert (
        results[2].incident_action
        == IncidentAction.NONE
    )
    assert len(
        repo.get_incident_events(
            incident_id
        )
    ) == 2


# 24
def test_closed_incident_then_new_degradation_opens_new_incident():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED,
            ControlPlaneHealthStatus.HEALTHY,
            ControlPlaneHealthStatus.DEGRADED,
        ],
    )

    assert repo.count_incidents(
        SUPPLIER
    ) == 2
    assert (
        results[0].incident_id
        != results[2].incident_id
    )


# 25
def test_active_incident_query_returns_open_incident():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED
        ],
    )

    active = repo.get_active_incident(
        SUPPLIER
    )

    assert active is not None
    assert (
        active.incident_id
        == results[0].incident_id
    )
    assert active.status == "open"


# 26
def test_active_incident_query_returns_none_after_recovery():
    _, connection_factory = factory()

    repo, _, _ = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED,
            ControlPlaneHealthStatus.HEALTHY,
        ],
    )

    assert (
        repo.get_active_incident(
            SUPPLIER
        )
        is None
    )


# 27
def test_incident_summary_reports_open_state():
    _, connection_factory = factory()

    repo, _, _ = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED
        ],
    )

    summary = (
        repo.get_incident_summaries(
            supplier_code=SUPPLIER,
            limit=1,
        )[0]
    )

    assert summary.status == "open"
    assert summary.closed_at is None
    assert summary.duration_seconds is None


# 28
def test_incident_summary_reports_closed_state():
    _, connection_factory = factory()

    repo, _, _ = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.DEGRADED,
            ControlPlaneHealthStatus.HEALTHY,
        ],
    )

    summary = (
        repo.get_incident_summaries(
            supplier_code=SUPPLIER,
            limit=1,
        )[0]
    )

    assert summary.status == "closed"
    assert (
        summary.latest_event_type
        == "incident_closed"
    )
    assert (
        summary.duration_seconds
        is not None
    )


# 29
def test_incident_summary_duration_uses_timestamps():
    connection, connection_factory = factory()

    ensure_supplier_incident_schema(
        connection
    )

    incident_id = "a" * 64

    connection.execute(
        """
        INSERT INTO supplier_incident_events (
            incident_id,
            supplier_code,
            source_health_event_id,
            event_type,
            health_status,
            health_score,
            created_at
        )
        VALUES (
            ?, ?, 1,
            'incident_opened',
            'degraded',
            70,
            '2026-11-20 10:00:00'
        );
        """,
        (
            incident_id,
            SUPPLIER,
        ),
    )

    connection.execute(
        """
        INSERT INTO supplier_incident_events (
            incident_id,
            supplier_code,
            source_health_event_id,
            event_type,
            health_status,
            health_score,
            created_at
        )
        VALUES (
            ?, ?, 2,
            'incident_closed',
            'healthy',
            100,
            '2026-11-20 10:05:30'
        );
        """,
        (
            incident_id,
            SUPPLIER,
        ),
    )
    connection.commit()

    repo = repository(
        connection_factory
    )

    summary = repo.get_incident_summaries(
        supplier_code=SUPPLIER,
        limit=1,
    )[0]

    assert (
        summary.duration_seconds
        == 330.0
    )


# 30
def test_mttr_averages_closed_incidents():
    connection, connection_factory = factory()

    ensure_supplier_incident_schema(
        connection
    )

    for index, seconds in (
        (1, 60),
        (2, 180),
    ):
        incident_id = (
            f"{index:064x}"
        )

        connection.execute(
            """
            INSERT INTO supplier_incident_events (
                incident_id,
                supplier_code,
                source_health_event_id,
                event_type,
                health_status,
                health_score,
                created_at
            )
            VALUES (?, ?, ?, 'incident_opened', 'degraded', 70, ?);
            """,
            (
                incident_id,
                SUPPLIER,
                index * 10,
                "2026-11-20 10:00:00",
            ),
        )

        close_time = (
            "2026-11-20 10:01:00"
            if seconds == 60
            else "2026-11-20 10:03:00"
        )

        connection.execute(
            """
            INSERT INTO supplier_incident_events (
                incident_id,
                supplier_code,
                source_health_event_id,
                event_type,
                health_status,
                health_score,
                created_at
            )
            VALUES (?, ?, ?, 'incident_closed', 'healthy', 100, ?);
            """,
            (
                incident_id,
                SUPPLIER,
                index * 10 + 1,
                close_time,
            ),
        )

    connection.commit()

    repo = repository(
        connection_factory
    )

    assert (
        repo.mean_time_to_recovery_seconds(
            SUPPLIER
        )
        == 120.0
    )


# 31
def test_open_incident_is_excluded_from_mttr():
    connection, connection_factory = factory()

    ensure_supplier_incident_schema(
        connection
    )

    connection.execute(
        """
        INSERT INTO supplier_incident_events (
            incident_id,
            supplier_code,
            source_health_event_id,
            event_type,
            health_status,
            health_score,
            created_at
        )
        VALUES (
            ?, ?, 1,
            'incident_opened',
            'critical',
            20,
            '2026-11-20 10:00:00'
        );
        """,
        (
            "a" * 64,
            SUPPLIER,
        ),
    )
    connection.commit()

    repo = repository(
        connection_factory
    )

    assert (
        repo.mean_time_to_recovery_seconds(
            SUPPLIER
        )
        is None
    )


# 32
def test_recent_health_events_are_newest_first():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.HEALTHY,
            ControlPlaneHealthStatus.DEGRADED,
            ControlPlaneHealthStatus.CRITICAL,
        ],
    )

    events = repo.get_recent_health_events(
        supplier_code=SUPPLIER,
        limit=3,
    )

    assert [
        event.health_status
        for event in events
    ] == [
        "critical",
        "degraded",
        "healthy",
    ]


# 33
def test_supplier_histories_are_isolated():
    _, connection_factory = factory()

    repo, svc = service(
        connection_factory
    )

    svc.record_health(
        report()
    )

    other = report()

    from dataclasses import replace

    svc.record_health(
        replace(
            other,
            supplier_code="other_supplier",
        )
    )

    assert repo.count_health_events(
        SUPPLIER
    ) == 1
    assert repo.count_health_events(
        "other_supplier"
    ) == 1


# 34
def test_identical_health_fingerprint_can_be_observed_twice():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.HEALTHY,
            ControlPlaneHealthStatus.HEALTHY,
        ],
    )

    assert (
        results[0]
        .health_event
        .health_fingerprint
        == results[1]
        .health_event
        .health_fingerprint
    )
    assert repo.count_health_events(
        SUPPLIER
    ) == 2


# 35
def test_slo_policy_fingerprint_is_preserved():
    _, connection_factory = factory()

    repo, svc = service(
        connection_factory
    )

    current = report(
        policy_fingerprint=(
            "f" * 64
        )
    )

    result = svc.record_health(
        current
    )

    assert (
        result.health_event
        .slo_policy_fingerprint
        == "f" * 64
    )


# 36
def test_reasons_are_preserved_as_json():
    _, connection_factory = factory()

    _, svc = service(
        connection_factory
    )

    result = svc.record_health(
        report(
            ControlPlaneHealthStatus.DEGRADED
        )
    )

    assert json.loads(
        result.health_event.reasons_json
    ) == [
        "healthy_run_ratio_below_target"
    ]


# 37
def test_recent_health_limit_validation():
    _, connection_factory = factory()

    repo = repository(
        connection_factory
    )

    with pytest.raises(
        ValueError,
        match="positive integer",
    ):
        repo.get_recent_health_events(
            supplier_code=SUPPLIER,
            limit=0,
        )


# 38
def test_incident_summary_limit_validation():
    _, connection_factory = factory()

    repo = repository(
        connection_factory
    )

    with pytest.raises(
        ValueError,
        match="positive integer",
    ):
        repo.get_incident_summaries(
            supplier_code=SUPPLIER,
            limit=0,
        )


# 39
def test_default_health_policy_matches_v27f_fingerprint_shape():
    fingerprint = (
        DEFAULT_CONTROL_PLANE_SLO_POLICY
        .fingerprint
    )

    assert len(
        fingerprint
    ) == 64
    assert all(
        character
        in "0123456789abcdef"
        for character
        in fingerprint
    )


# 40
def test_full_incident_lifecycle_event_order():
    _, connection_factory = factory()

    repo, _, results = record_sequence(
        connection_factory,
        [
            ControlPlaneHealthStatus.HEALTHY,
            ControlPlaneHealthStatus.DEGRADED,
            ControlPlaneHealthStatus.CRITICAL,
            ControlPlaneHealthStatus.DEGRADED,
            ControlPlaneHealthStatus.HEALTHY,
        ],
    )

    incident_id = results[1].incident_id

    assert [
        event.event_type
        for event
        in repo.get_incident_events(
            incident_id
        )
    ] == [
        "incident_opened",
        "incident_escalated",
        "incident_deescalated",
        "incident_closed",
    ]
