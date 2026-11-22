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


from supplier.orchestration.alert_policy import (  # noqa: E402
    DEFAULT_INCIDENT_ALERT_ROUTING_POLICY,
)
from supplier.orchestration.alert_repository import (  # noqa: E402
    SupplierIncidentAlertRepository,
)
from supplier.orchestration.alert_service import (  # noqa: E402
    SupplierIncidentAlertRoutingService,
)
from supplier.orchestration.bootstrap import (  # noqa: E402
    SUPPLIER_CODE,
)
from supplier.orchestration.incident_repository import (  # noqa: E402
    SupplierIncidentRepository,
)


def main() -> int:
    incident_repository = (
        SupplierIncidentRepository()
    )

    alert_repository = (
        SupplierIncidentAlertRepository()
    )

    service = (
        SupplierIncidentAlertRoutingService(
            incident_repository=(
                incident_repository
            ),
            alert_repository=(
                alert_repository
            ),
            policy=(
                DEFAULT_INCIDENT_ALERT_ROUTING_POLICY
            ),
        )
    )

    result = (
        service.route_existing_incidents(
            supplier_code=(
                SUPPLIER_CODE
            ),
            limit=20,
        )
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 INCIDENT ALERT ROUTER"
    )
    print("=" * 72)
    print(
        "MODE: ROUTING AUDIT ONLY"
    )
    print(
        "EXTERNAL NOTIFICATION DELIVERY: DISABLED"
    )
    print(
        "LIVE SHOPIFY EXECUTION: DISABLED"
    )
    print("-" * 72)

    print(
        "ALERT ROUTING POLICY"
    )
    print("-" * 72)
    print(
        "Policy fingerprint:"
    )
    print(
        DEFAULT_INCIDENT_ALERT_ROUTING_POLICY
        .fingerprint
    )
    print(
        "Degraded routes: "
        + ", ".join(
            route.value
            for route
            in DEFAULT_INCIDENT_ALERT_ROUTING_POLICY
            .degraded_routes
        )
    )
    print(
        "Critical routes: "
        + ", ".join(
            route.value
            for route
            in DEFAULT_INCIDENT_ALERT_ROUTING_POLICY
            .critical_routes
        )
    )
    print(
        "Recovery routes: "
        + ", ".join(
            route.value
            for route
            in DEFAULT_INCIDENT_ALERT_ROUTING_POLICY
            .recovery_routes
        )
    )
    print("-" * 72)

    print(
        "SCAN RESULT"
    )
    print("-" * 72)
    print(
        f"Incidents seen: "
        f"{result.incidents_seen}"
    )
    print(
        f"Incident events seen: "
        f"{result.incident_events_seen}"
    )
    print(
        f"Routing decisions: "
        f"{result.routing_decisions}"
    )
    print(
        f"Routes planned: "
        f"{result.routes_planned}"
    )
    print(
        f"Routes written now: "
        f"{result.routes_written}"
    )
    print(
        "Routes already recorded: "
        f"{result.routes_already_recorded}"
    )
    print(
        "Total stored routes: "
        f"{alert_repository.count_routes(SUPPLIER_CODE)}"
    )
    print()
    print(
        "SHOPIFY WRITES PERFORMED: 0"
    )
    print(
        "EXTERNAL ALERTS SENT: 0"
    )
    print(
        "SQLITE AUDIT WRITES: "
        + (
            "ENABLED"
            if result.routes_written > 0
            else "0"
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
