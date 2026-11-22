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


from supplier.orchestration.alert_repository import (  # noqa: E402
    SupplierIncidentAlertRepository,
)
from supplier.orchestration.bootstrap import (  # noqa: E402
    SUPPLIER_CODE,
)


def main() -> int:
    repository = (
        SupplierIncidentAlertRepository()
    )

    repository.ensure_schema()

    routes = repository.get_recent_routes(
        supplier_code=SUPPLIER_CODE,
        limit=50,
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 INCIDENT ALERT ROUTING HISTORY"
    )
    print("=" * 72)
    print(
        "LEDGER MODE: APPEND ONLY"
    )
    print(
        "DELIVERY MODE: ROUTING AUDIT ONLY"
    )
    print(
        f"Supplier: {SUPPLIER_CODE}"
    )
    print(
        f"Routes stored: "
        f"{repository.count_routes(SUPPLIER_CODE)}"
    )
    print(
        "Critical routes: "
        f"{repository.count_routes_by_severity(supplier_code=SUPPLIER_CODE, severity='critical')}"
    )
    print(
        "Warning routes: "
        f"{repository.count_routes_by_severity(supplier_code=SUPPLIER_CODE, severity='warning')}"
    )
    print(
        "Info routes: "
        f"{repository.count_routes_by_severity(supplier_code=SUPPLIER_CODE, severity='info')}"
    )
    print("-" * 72)

    if not routes:
        print(
            "No incident alert routes recorded."
        )
        return 0

    for route in routes:
        print(
            f"Route #{route.route_event_id}"
        )
        print(
            f"  Incident: "
            f"{route.incident_id}"
        )
        print(
            f"  Source event: "
            f"{route.source_event_type.upper()}"
        )
        print(
            f"  Severity: "
            f"{route.severity.upper()}"
        )
        print(
            f"  Route: "
            f"{route.route.upper()}"
        )
        print(
            f"  Recorded: "
            f"{route.created_at}"
        )
        print("-" * 72)

    print()
    print(
        "EXTERNAL ALERTS SENT: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
