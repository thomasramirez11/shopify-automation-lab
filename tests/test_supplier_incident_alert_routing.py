import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from database.supplier_incident_alert_schema import (
    ensure_supplier_incident_alert_schema,
)
from supplier.orchestration.alert_models import (
    AlertRoutingError,
    IncidentAlertRoute,
    IncidentAlertSeverity,
)
from supplier.orchestration.alert_policy import (
    IncidentAlertRoutingPolicy,
    build_alert_route_fingerprint,
    evaluate_incident_alert_routing,
)
from supplier.orchestration.alert_repository import (
    SupplierIncidentAlertRepository,
)
from supplier.orchestration.alert_service import (
    SupplierIncidentAlertRoutingService,
)
from supplier.orchestration.incident_repository import (
    SupplierIncidentRepository,
)


SUPPLIER = "demo_supplier"
INCIDENT_ID = "a" * 64


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


def incident_event(
    *,
    event_id=1,
    event_type="incident_opened",
    health_status="degraded",
    health_score=70,
    incident_id=INCIDENT_ID,
):
    return SimpleNamespace(
        incident_event_id=event_id,
        incident_id=incident_id,
        supplier_code=SUPPLIER,
        source_health_event_id=event_id,
        event_type=event_type,
        health_status=health_status,
        health_score=health_score,
        created_at="2026-11-20 10:00:00",
    )


def alert_repository(
    connection_factory,
):
    return SupplierIncidentAlertRepository(
        connection_factory=(
            connection_factory
        )
    )


def incident_repository(
    connection_factory,
):
    return SupplierIncidentRepository(
        connection_factory=(
            connection_factory
        )
    )


def routing_service(
    connection_factory,
    *,
    policy=None,
):
    return SupplierIncidentAlertRoutingService(
        incident_repository=(
            incident_repository(
                connection_factory
            )
        ),
        alert_repository=(
            alert_repository(
                connection_factory
            )
        ),
        policy=(
            policy
            if policy is not None
            else IncidentAlertRoutingPolicy()
        ),
    )


def seed_incident_event(
    connection,
    *,
    event_id,
    incident_id,
    event_type,
    health_status,
    health_score,
    created_at,
):
    ensure_supplier_incident_alert_schema(
        connection
    )

    connection.execute(
        """
        INSERT INTO supplier_incident_events (
            incident_event_id,
            incident_id,
            supplier_code,
            source_health_event_id,
            event_type,
            health_status,
            health_score,
            created_at
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?
        );
        """,
        (
            event_id,
            incident_id,
            SUPPLIER,
            event_id,
            event_type,
            health_status,
            health_score,
            created_at,
        ),
    )
    connection.commit()


def test_schema_creates_alert_route_table():
    connection, _ = factory()

    ensure_supplier_incident_alert_schema(
        connection
    )

    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'supplier_incident_alert_routes';
        """
    ).fetchone()

    assert row is not None


def test_schema_is_idempotent():
    connection, _ = factory()

    ensure_supplier_incident_alert_schema(
        connection
    )
    ensure_supplier_incident_alert_schema(
        connection
    )


def test_alert_route_ledger_update_is_blocked():
    connection, connection_factory = factory()

    service = routing_service(
        connection_factory
    )

    service.route_incident_event(
        incident_event()
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            UPDATE supplier_incident_alert_routes
            SET severity = 'critical';
            """
        )


def test_alert_route_ledger_delete_is_blocked():
    connection, connection_factory = factory()

    service = routing_service(
        connection_factory
    )

    service.route_incident_event(
        incident_event()
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            DELETE FROM supplier_incident_alert_routes;
            """
        )


def test_degraded_open_is_warning():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event()
    )

    assert (
        decision.severity
        == IncidentAlertSeverity.WARNING
    )


def test_degraded_open_routes_dashboard_and_operator():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event()
    )

    assert decision.routes == (
        IncidentAlertRoute.DASHBOARD,
        IncidentAlertRoute.OPERATOR_REVIEW,
    )


def test_critical_open_is_critical():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event(
            health_status="critical",
            health_score=20,
        )
    )

    assert (
        decision.severity
        == IncidentAlertSeverity.CRITICAL
    )


def test_critical_open_includes_immediate_alert():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event(
            health_status="critical",
            health_score=20,
        )
    )

    assert (
        IncidentAlertRoute.IMMEDIATE_ALERT
        in decision.routes
    )


def test_escalated_event_routes_as_critical():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event(
            event_type="incident_escalated",
            health_status="critical",
            health_score=20,
        )
    )

    assert (
        decision.severity
        == IncidentAlertSeverity.CRITICAL
    )
    assert (
        decision.reason
        == "incident_escalated_to_critical"
    )


def test_deescalated_event_remains_warning():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event(
            event_type="incident_deescalated",
            health_status="degraded",
            health_score=65,
        )
    )

    assert (
        decision.severity
        == IncidentAlertSeverity.WARNING
    )


def test_closed_event_is_info():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event(
            event_type="incident_closed",
            health_status="healthy",
            health_score=100,
        )
    )

    assert (
        decision.severity
        == IncidentAlertSeverity.INFO
    )


def test_closed_event_routes_recovery_notice():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event(
            event_type="incident_closed",
            health_status="healthy",
            health_score=100,
        )
    )

    assert decision.routes == (
        IncidentAlertRoute.DASHBOARD,
        IncidentAlertRoute.RECOVERY_NOTICE,
    )


def test_policy_fingerprint_is_deterministic():
    first = IncidentAlertRoutingPolicy()
    second = IncidentAlertRoutingPolicy()

    assert (
        first.fingerprint
        == second.fingerprint
    )


def test_policy_fingerprint_changes_with_route():
    first = IncidentAlertRoutingPolicy()

    second = IncidentAlertRoutingPolicy(
        degraded_routes=(
            IncidentAlertRoute.DASHBOARD,
        )
    )

    assert (
        first.fingerprint
        != second.fingerprint
    )


def test_duplicate_policy_routes_are_rejected():
    with pytest.raises(
        AlertRoutingError,
        match="duplicate",
    ):
        IncidentAlertRoutingPolicy(
            degraded_routes=(
                IncidentAlertRoute.DASHBOARD,
                IncidentAlertRoute.DASHBOARD,
            )
        )


def test_empty_policy_route_group_is_rejected():
    with pytest.raises(
        AlertRoutingError,
        match="non-empty tuple",
    ):
        IncidentAlertRoutingPolicy(
            critical_routes=()
        )


def test_invalid_event_combination_is_rejected():
    with pytest.raises(
        AlertRoutingError,
        match="Unsupported",
    ):
        evaluate_incident_alert_routing(
            incident_event=incident_event(
                event_type="incident_opened",
                health_status="healthy",
                health_score=100,
            )
        )


def test_route_fingerprint_is_deterministic():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event()
    )

    route = decision.routes[0]

    assert (
        build_alert_route_fingerprint(
            decision=decision,
            route=route,
        )
        == build_alert_route_fingerprint(
            decision=decision,
            route=route,
        )
    )


def test_route_fingerprint_changes_with_route():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event()
    )

    first = build_alert_route_fingerprint(
        decision=decision,
        route=(
            IncidentAlertRoute.DASHBOARD
        ),
    )

    second = build_alert_route_fingerprint(
        decision=decision,
        route=(
            IncidentAlertRoute.OPERATOR_REVIEW
        ),
    )

    assert first != second


def test_route_fingerprint_ignores_policy_version():
    event = incident_event()

    first_decision = evaluate_incident_alert_routing(
        incident_event=event,
        policy=IncidentAlertRoutingPolicy(),
    )

    second_decision = evaluate_incident_alert_routing(
        incident_event=event,
        policy=IncidentAlertRoutingPolicy(
            degraded_routes=(
                IncidentAlertRoute.DASHBOARD,
                IncidentAlertRoute.OPERATOR_REVIEW,
                IncidentAlertRoute.IMMEDIATE_ALERT,
            )
        ),
    )

    assert (
        build_alert_route_fingerprint(
            decision=first_decision,
            route=(
                IncidentAlertRoute.DASHBOARD
            ),
        )
        == build_alert_route_fingerprint(
            decision=second_decision,
            route=(
                IncidentAlertRoute.DASHBOARD
            ),
        )
    )


def test_routing_degraded_writes_two_routes():
    _, connection_factory = factory()

    service = routing_service(
        connection_factory
    )

    result = service.route_incident_event(
        incident_event()
    )

    assert result.routes_planned == 2
    assert result.routes_written == 2
    assert (
        result.routes_already_recorded
        == 0
    )


def test_routing_critical_writes_three_routes():
    _, connection_factory = factory()

    service = routing_service(
        connection_factory
    )

    result = service.route_incident_event(
        incident_event(
            health_status="critical",
            health_score=20,
        )
    )

    assert result.routes_planned == 3
    assert result.routes_written == 3


def test_routing_closed_writes_two_routes():
    _, connection_factory = factory()

    service = routing_service(
        connection_factory
    )

    result = service.route_incident_event(
        incident_event(
            event_type="incident_closed",
            health_status="healthy",
            health_score=100,
        )
    )

    assert result.routes_planned == 2
    assert result.routes_written == 2


def test_repeated_routing_is_idempotent():
    _, connection_factory = factory()

    service = routing_service(
        connection_factory
    )

    first = service.route_incident_event(
        incident_event()
    )

    second = service.route_incident_event(
        incident_event()
    )

    assert first.routes_written == 2
    assert second.routes_written == 0
    assert (
        second.routes_already_recorded
        == 2
    )


def test_policy_change_can_add_new_route_without_duplication():
    _, connection_factory = factory()

    first_service = routing_service(
        connection_factory,
        policy=IncidentAlertRoutingPolicy(
            degraded_routes=(
                IncidentAlertRoute.DASHBOARD,
                IncidentAlertRoute.OPERATOR_REVIEW,
            )
        ),
    )

    first_service.route_incident_event(
        incident_event()
    )

    second_service = routing_service(
        connection_factory,
        policy=IncidentAlertRoutingPolicy(
            degraded_routes=(
                IncidentAlertRoute.DASHBOARD,
                IncidentAlertRoute.OPERATOR_REVIEW,
                IncidentAlertRoute.IMMEDIATE_ALERT,
            )
        ),
    )

    result = second_service.route_incident_event(
        incident_event()
    )

    assert result.routes_written == 1
    assert (
        result.routes_already_recorded
        == 2
    )


def test_repository_returns_incident_routes_in_order():
    _, connection_factory = factory()

    repo = alert_repository(
        connection_factory
    )

    service = SupplierIncidentAlertRoutingService(
        incident_repository=(
            incident_repository(
                connection_factory
            )
        ),
        alert_repository=repo,
    )

    service.route_incident_event(
        incident_event()
    )

    routes = repo.get_routes_for_incident(
        INCIDENT_ID
    )

    assert [
        route.route
        for route in routes
    ] == [
        "dashboard",
        "operator_review",
    ]


def test_recent_routes_are_newest_first():
    _, connection_factory = factory()

    repo = alert_repository(
        connection_factory
    )

    service = SupplierIncidentAlertRoutingService(
        incident_repository=(
            incident_repository(
                connection_factory
            )
        ),
        alert_repository=repo,
    )

    service.route_incident_event(
        incident_event(
            event_id=1,
        )
    )

    service.route_incident_event(
        incident_event(
            event_id=2,
            event_type="incident_escalated",
            health_status="critical",
            health_score=20,
        )
    )

    routes = repo.get_recent_routes(
        supplier_code=SUPPLIER,
        limit=5,
    )

    assert (
        routes[0].source_incident_event_id
        == 2
    )


def test_recent_route_limit_validation():
    _, connection_factory = factory()

    repo = alert_repository(
        connection_factory
    )

    with pytest.raises(
        ValueError,
        match="positive integer",
    ):
        repo.get_recent_routes(
            supplier_code=SUPPLIER,
            limit=0,
        )


def test_count_routes_by_severity():
    _, connection_factory = factory()

    repo = alert_repository(
        connection_factory
    )

    service = SupplierIncidentAlertRoutingService(
        incident_repository=(
            incident_repository(
                connection_factory
            )
        ),
        alert_repository=repo,
    )

    service.route_incident_event(
        incident_event()
    )

    service.route_incident_event(
        incident_event(
            event_id=2,
            event_type="incident_escalated",
            health_status="critical",
            health_score=20,
        )
    )

    assert (
        repo.count_routes_by_severity(
            supplier_code=SUPPLIER,
            severity="warning",
        )
        == 2
    )

    assert (
        repo.count_routes_by_severity(
            supplier_code=SUPPLIER,
            severity="critical",
        )
        == 3
    )


def test_empty_incident_scan_writes_nothing():
    _, connection_factory = factory()

    service = routing_service(
        connection_factory
    )

    result = service.route_existing_incidents(
        supplier_code=SUPPLIER,
        limit=20,
    )

    assert result.incidents_seen == 0
    assert result.routes_written == 0


def test_scan_routes_full_incident_lifecycle():
    connection, connection_factory = factory()

    seed_incident_event(
        connection,
        event_id=1,
        incident_id=INCIDENT_ID,
        event_type="incident_opened",
        health_status="degraded",
        health_score=70,
        created_at="2026-11-20 10:00:00",
    )

    seed_incident_event(
        connection,
        event_id=2,
        incident_id=INCIDENT_ID,
        event_type="incident_escalated",
        health_status="critical",
        health_score=20,
        created_at="2026-11-20 10:01:00",
    )

    seed_incident_event(
        connection,
        event_id=3,
        incident_id=INCIDENT_ID,
        event_type="incident_deescalated",
        health_status="degraded",
        health_score=65,
        created_at="2026-11-20 10:02:00",
    )

    seed_incident_event(
        connection,
        event_id=4,
        incident_id=INCIDENT_ID,
        event_type="incident_closed",
        health_status="healthy",
        health_score=100,
        created_at="2026-11-20 10:03:00",
    )

    service = routing_service(
        connection_factory
    )

    result = service.route_existing_incidents(
        supplier_code=SUPPLIER,
        limit=20,
    )

    assert result.incidents_seen == 1
    assert result.incident_events_seen == 4
    assert result.routing_decisions == 4
    assert result.routes_planned == 9
    assert result.routes_written == 9


def test_rescan_full_lifecycle_is_fully_deduplicated():
    connection, connection_factory = factory()

    for event_id, event_type, status, score in (
        (
            1,
            "incident_opened",
            "degraded",
            70,
        ),
        (
            2,
            "incident_escalated",
            "critical",
            20,
        ),
        (
            3,
            "incident_deescalated",
            "degraded",
            65,
        ),
        (
            4,
            "incident_closed",
            "healthy",
            100,
        ),
    ):
        seed_incident_event(
            connection,
            event_id=event_id,
            incident_id=INCIDENT_ID,
            event_type=event_type,
            health_status=status,
            health_score=score,
            created_at=(
                f"2026-11-20 10:0{event_id}:00"
            ),
        )

    service = routing_service(
        connection_factory
    )

    first = service.route_existing_incidents(
        supplier_code=SUPPLIER,
        limit=20,
    )

    second = service.route_existing_incidents(
        supplier_code=SUPPLIER,
        limit=20,
    )

    assert first.routes_written == 9
    assert second.routes_written == 0
    assert (
        second.routes_already_recorded
        == 9
    )


def test_scan_uses_all_events_not_only_latest():
    connection, connection_factory = factory()

    seed_incident_event(
        connection,
        event_id=1,
        incident_id=INCIDENT_ID,
        event_type="incident_opened",
        health_status="critical",
        health_score=20,
        created_at="2026-11-20 10:00:00",
    )

    seed_incident_event(
        connection,
        event_id=2,
        incident_id=INCIDENT_ID,
        event_type="incident_closed",
        health_status="healthy",
        health_score=100,
        created_at="2026-11-20 10:03:00",
    )

    service = routing_service(
        connection_factory
    )

    result = service.route_existing_incidents(
        supplier_code=SUPPLIER,
        limit=20,
    )

    assert result.incident_events_seen == 2
    assert result.routes_planned == 5


def test_policy_fingerprint_is_persisted():
    _, connection_factory = factory()

    repo = alert_repository(
        connection_factory
    )

    policy = IncidentAlertRoutingPolicy()

    service = SupplierIncidentAlertRoutingService(
        incident_repository=(
            incident_repository(
                connection_factory
            )
        ),
        alert_repository=repo,
        policy=policy,
    )

    service.route_incident_event(
        incident_event()
    )

    routes = repo.get_routes_for_incident(
        INCIDENT_ID
    )

    assert all(
        route.policy_fingerprint
        == policy.fingerprint
        for route in routes
    )


def test_route_fingerprint_is_persisted():
    _, connection_factory = factory()

    repo = alert_repository(
        connection_factory
    )

    service = SupplierIncidentAlertRoutingService(
        incident_repository=(
            incident_repository(
                connection_factory
            )
        ),
        alert_repository=repo,
    )

    result = service.route_incident_event(
        incident_event()
    )

    assert all(
        len(
            route.route_fingerprint
        )
        == 64
        for route
        in result.stored_routes
    )


def test_external_delivery_is_not_part_of_result_model():
    _, connection_factory = factory()

    service = routing_service(
        connection_factory
    )

    result = service.route_incident_event(
        incident_event()
    )

    assert not hasattr(
        result,
        "sent"
    )
    assert not hasattr(
        result,
        "delivered"
    )


def test_critical_route_contains_all_three_default_channels():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event(
            health_status="critical",
            health_score=20,
        )
    )

    assert set(
        decision.routes
    ) == {
        IncidentAlertRoute.DASHBOARD,
        IncidentAlertRoute.OPERATOR_REVIEW,
        IncidentAlertRoute.IMMEDIATE_ALERT,
    }


def test_recovery_does_not_route_immediate_alert():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event(
            event_type="incident_closed",
            health_status="healthy",
            health_score=100,
        )
    )

    assert (
        IncidentAlertRoute.IMMEDIATE_ALERT
        not in decision.routes
    )


def test_warning_does_not_route_recovery_notice():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event()
    )

    assert (
        IncidentAlertRoute.RECOVERY_NOTICE
        not in decision.routes
    )


def test_incident_reason_is_explicit_for_degraded_open():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event()
    )

    assert (
        decision.reason
        == "degraded_incident"
    )


def test_incident_reason_is_explicit_for_recovery():
    decision = evaluate_incident_alert_routing(
        incident_event=incident_event(
            event_type="incident_closed",
            health_status="healthy",
            health_score=100,
        )
    )

    assert (
        decision.reason
        == "incident_recovered"
    )
