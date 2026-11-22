from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


from supplier.orchestration.alert_repository import (  # noqa: E402
    SupplierIncidentAlertRepository,
)
from supplier.orchestration.alert_service import (  # noqa: E402
    SupplierIncidentAlertRoutingService,
)
from supplier.orchestration.health_models import (  # noqa: E402
    ControlPlaneHealthReport,
    ControlPlaneHealthStatus,
    HealthReason,
    SLOCheck,
)
from supplier.orchestration.incident_repository import (  # noqa: E402
    SupplierIncidentRepository,
)
from supplier.orchestration.incident_service import (  # noqa: E402
    SupplierIncidentMonitoringService,
)


def report(
    status,
    score,
):
    healthy = (
        status
        == ControlPlaneHealthStatus.HEALTHY
    )

    return ControlPlaneHealthReport(
        supplier_code="synthetic_alert_supplier",
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
            0
            if status
            != ControlPlaneHealthStatus.CRITICAL
            else 1
        ),
        queued_retry_attempts=(
            0
            if healthy
            else 1
        ),
        slo_checks=(
            SLOCheck(
                name="demo",
                met=healthy,
                observed=(
                    "pass"
                    if healthy
                    else "fail"
                ),
                target="pass",
            ),
        ),
        reasons=(
            (
                HealthReason.ALL_SLOS_MET,
            )
            if healthy
            else (
                HealthReason
                .HEALTHY_RUN_RATIO_BELOW_TARGET,
            )
        ),
        slo_policy_fingerprint=(
            "a" * 64
        ),
    )


def main() -> int:
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

    incident_repository = (
        SupplierIncidentRepository(
            connection_factory=(
                connection_factory
            )
        )
    )

    alert_repository = (
        SupplierIncidentAlertRepository(
            connection_factory=(
                connection_factory
            )
        )
    )

    incident_service = (
        SupplierIncidentMonitoringService(
            incident_repository
        )
    )

    alert_service = (
        SupplierIncidentAlertRoutingService(
            incident_repository=(
                incident_repository
            ),
            alert_repository=(
                alert_repository
            ),
        )
    )

    sequence = (
        (
            ControlPlaneHealthStatus.DEGRADED,
            72,
        ),
        (
            ControlPlaneHealthStatus.CRITICAL,
            25,
        ),
        (
            ControlPlaneHealthStatus.DEGRADED,
            68,
        ),
        (
            ControlPlaneHealthStatus.HEALTHY,
            100,
        ),
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 SYNTHETIC INCIDENT ALERT ROUTING"
    )
    print("=" * 72)
    print(
        "DATABASE: IN-MEMORY ONLY"
    )
    print(
        "EXTERNAL NOTIFICATION DELIVERY: DISABLED"
    )
    print("-" * 72)

    for status, score in sequence:
        monitor_result = (
            incident_service.record_health(
                report(
                    status,
                    score,
                )
            )
        )

        if (
            monitor_result.incident_event_id
            is None
        ):
            continue

        event = (
            incident_repository
            .get_latest_incident_event(
                monitor_result.incident_id
            )
        )

        routing = (
            alert_service
            .route_incident_event(
                event
            )
        )

        print(
            f"{event.event_type.upper()} "
            f"| health={event.health_status.upper()} "
            f"| severity={routing.decision.severity.value.upper()}"
        )
        print(
            "  routes="
            + ", ".join(
                route.value
                for route
                in routing.decision.routes
            )
        )
        print(
            f"  routes_written="
            f"{routing.routes_written}"
        )

    print("-" * 72)

    scan_again = (
        alert_service.route_existing_incidents(
            supplier_code=(
                "synthetic_alert_supplier"
            ),
            limit=10,
        )
    )

    print(
        "DEDUPLICATION RE-SCAN"
    )
    print(
        f"Routes written on re-scan: "
        f"{scan_again.routes_written}"
    )
    print(
        "Routes already recorded: "
        f"{scan_again.routes_already_recorded}"
    )
    print(
        "Total stored routes: "
        f"{alert_repository.count_routes('synthetic_alert_supplier')}"
    )
    print(
        "EXTERNAL ALERTS SENT: 0"
    )
    print(
        "REAL SQLITE DATABASE WRITES: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
