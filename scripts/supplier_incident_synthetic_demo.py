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


def demo_report(
    status,
    score,
):
    healthy = (
        status
        == ControlPlaneHealthStatus.HEALTHY
    )

    return ControlPlaneHealthReport(
        supplier_code="synthetic_demo_supplier",
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

    repository = SupplierIncidentRepository(
        connection_factory=(
            connection_factory
        )
    )

    service = SupplierIncidentMonitoringService(
        repository
    )

    sequence = (
        (
            ControlPlaneHealthStatus.HEALTHY,
            100,
        ),
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
        "V2.7 SYNTHETIC INCIDENT LIFECYCLE"
    )
    print("=" * 72)
    print(
        "DATABASE: IN-MEMORY ONLY"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )
    print("-" * 72)

    for index, (
        status,
        score,
    ) in enumerate(
        sequence,
        start=1,
    ):
        result = service.record_health(
            demo_report(
                status,
                score,
            )
        )

        print(
            f"Observation #{index}: "
            f"{status.value.upper()} "
            f"| score={score}"
        )
        print(
            f"  health transition="
            f"{result.health_transition.value.upper()}"
        )
        print(
            f"  incident action="
            f"{result.incident_action.value.upper()}"
        )
        print(
            "  incident="
            + (
                result.incident_id
                if result.incident_id
                else "NONE"
            )
        )

    print("-" * 72)

    incidents = (
        repository.get_incident_summaries(
            supplier_code=(
                "synthetic_demo_supplier"
            ),
            limit=10,
        )
    )

    print(
        f"Incidents opened: "
        f"{len(incidents)}"
    )
    print(
        f"Open incidents: "
        f"{repository.count_open_incidents('synthetic_demo_supplier')}"
    )

    if incidents:
        incident = incidents[0]
        print(
            f"Final incident status: "
            f"{incident.status.upper()}"
        )
        print(
            f"Latest event: "
            f"{incident.latest_event_type.upper()}"
        )

    print(
        "REAL SQLITE DATABASE WRITES: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
