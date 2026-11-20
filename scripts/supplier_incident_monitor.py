from __future__ import annotations

import sys
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


from supplier.orchestration.bootstrap import (  # noqa: E402
    SUPPLIER_CODE,
    build_default_supplier_operations_orchestrator,
)
from supplier.orchestration.health_engine import (  # noqa: E402
    evaluate_control_plane_health,
)
from supplier.orchestration.health_policy import (  # noqa: E402
    DEFAULT_CONTROL_PLANE_SLO_POLICY,
)
from supplier.orchestration.incident_repository import (  # noqa: E402
    SupplierIncidentRepository,
)
from supplier.orchestration.incident_service import (  # noqa: E402
    SupplierIncidentMonitoringService,
)
from supplier.orchestration.run_repository import (  # noqa: E402
    SupplierOrchestrationRunRepository,
)


def main() -> int:
    health_policy = (
        DEFAULT_CONTROL_PLANE_SLO_POLICY
    )

    snapshot = (
        build_default_supplier_operations_orchestrator(
            PROJECT_ROOT
        )
        .build_snapshot()
    )

    run_repository = (
        SupplierOrchestrationRunRepository()
    )

    recent_runs = (
        run_repository.get_recent(
            supplier_code=SUPPLIER_CODE,
            limit=(
                health_policy
                .history_window_runs
            ),
        )
    )

    report = evaluate_control_plane_health(
        snapshot=snapshot,
        recent_runs=recent_runs,
        policy=health_policy,
    )

    repository = (
        SupplierIncidentRepository()
    )

    result = (
        SupplierIncidentMonitoringService(
            repository
        )
        .record_health(
            report
        )
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 INCIDENT MONITOR"
    )
    print("=" * 72)
    print(
        "MODE: HEALTH OBSERVATION + INCIDENT AUDIT"
    )
    print(
        "LIVE SHOPIFY EXECUTION: DISABLED"
    )
    print(
        "SQLITE BUSINESS WRITES: 0"
    )
    print("-" * 72)

    print(
        "HEALTH OBSERVATION"
    )
    print("-" * 72)
    print(
        f"Health event ID: "
        f"#{result.health_event.health_event_id}"
    )
    print(
        f"Health status: "
        f"{result.health_event.health_status.upper()}"
    )
    print(
        f"Health score: "
        f"{result.health_event.health_score}/100"
    )
    print(
        f"Health transition: "
        f"{result.health_transition.value.upper()}"
    )
    print(
        f"Status changed: "
        f"{bool(result.health_event.status_changed)}"
    )
    print("-" * 72)

    print(
        "INCIDENT DECISION"
    )
    print("-" * 72)
    print(
        f"Incident action: "
        f"{result.incident_action.value.upper()}"
    )
    print(
        "Incident ID: "
        + (
            result.incident_id
            if result.incident_id
            is not None
            else "NONE"
        )
    )
    print(
        f"Open incidents: "
        f"{repository.count_open_incidents(SUPPLIER_CODE)}"
    )
    print(
        f"Total incidents: "
        f"{repository.count_incidents(SUPPLIER_CODE)}"
    )
    print(
        f"Health observations stored: "
        f"{repository.count_health_events(SUPPLIER_CODE)}"
    )

    mttr = (
        repository
        .mean_time_to_recovery_seconds(
            SUPPLIER_CODE
        )
    )

    print(
        "MTTR seconds: "
        + (
            f"{mttr:.2f}"
            if mttr is not None
            else "N/A"
        )
    )
    print()
    print(
        "SHOPIFY WRITES PERFORMED: 0"
    )
    print(
        "SQLITE AUDIT WRITES: ENABLED"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
