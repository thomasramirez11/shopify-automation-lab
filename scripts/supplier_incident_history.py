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
)
from supplier.orchestration.incident_repository import (  # noqa: E402
    SupplierIncidentRepository,
)


def main() -> int:
    repository = (
        SupplierIncidentRepository()
    )

    repository.ensure_schema()

    health_events = (
        repository.get_recent_health_events(
            supplier_code=SUPPLIER_CODE,
            limit=10,
        )
    )

    incidents = (
        repository.get_incident_summaries(
            supplier_code=SUPPLIER_CODE,
            limit=10,
        )
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 INCIDENT + HEALTH HISTORY"
    )
    print("=" * 72)
    print(
        "LEDGER MODE: APPEND ONLY"
    )
    print(
        f"Supplier: "
        f"{SUPPLIER_CODE}"
    )
    print(
        f"Health observations: "
        f"{repository.count_health_events(SUPPLIER_CODE)}"
    )
    print(
        f"Incidents: "
        f"{repository.count_incidents(SUPPLIER_CODE)}"
    )
    print(
        f"Open incidents: "
        f"{repository.count_open_incidents(SUPPLIER_CODE)}"
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
    print("-" * 72)

    print(
        "RECENT HEALTH OBSERVATIONS"
    )
    print("-" * 72)

    if not health_events:
        print(
            "No health observations recorded."
        )

    for event in health_events:
        print(
            f"Health #{event.health_event_id} "
            f"| {event.health_status.upper()} "
            f"| score={event.health_score} "
            f"| changed={bool(event.status_changed)} "
            f"| {event.created_at}"
        )

    print("-" * 72)
    print(
        "INCIDENTS"
    )
    print("-" * 72)

    if not incidents:
        print(
            "No incidents recorded."
        )

    for incident in incidents:
        print(
            f"Incident: "
            f"{incident.incident_id}"
        )
        print(
            f"  Status: "
            f"{incident.status.upper()}"
        )
        print(
            f"  Opened as: "
            f"{incident.opening_health_status.upper()}"
        )
        print(
            f"  Latest health: "
            f"{incident.latest_health_status.upper()}"
        )
        print(
            f"  Latest event: "
            f"{incident.latest_event_type.upper()}"
        )
        print(
            f"  Opened: "
            f"{incident.opened_at}"
        )
        print(
            f"  Closed: "
            f"{incident.closed_at or 'OPEN'}"
        )
        print(
            "  Recovery seconds: "
            + (
                f"{incident.duration_seconds:.2f}"
                if incident.duration_seconds
                is not None
                else "OPEN"
            )
        )

    print()
    print(
        "SHOPIFY WRITES PERFORMED: 0"
    )
    print(
        "SQLITE WRITES PERFORMED: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
