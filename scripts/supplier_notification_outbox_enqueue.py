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
from supplier.orchestration.outbox_repository import (  # noqa: E402
    SupplierNotificationOutboxRepository,
)
from supplier.orchestration.outbox_service import (  # noqa: E402
    SupplierNotificationOutboxService,
)


def main() -> int:
    outbox_repository = (
        SupplierNotificationOutboxRepository()
    )

    service = (
        SupplierNotificationOutboxService(
            alert_repository=(
                SupplierIncidentAlertRepository()
            ),
            outbox_repository=(
                outbox_repository
            ),
        )
    )

    result = (
        service.enqueue_existing_alert_routes(
            supplier_code=(
                SUPPLIER_CODE
            ),
            limit=100,
        )
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 DURABLE NOTIFICATION OUTBOX ENQUEUE"
    )
    print("=" * 72)
    print(
        "MODE: DURABLE QUEUE ONLY"
    )
    print(
        "EXTERNAL NOTIFICATION DELIVERY: DISABLED"
    )
    print("-" * 72)

    print(
        f"Alert routes seen: "
        f"{result.alert_routes_seen}"
    )
    print(
        f"External messages planned: "
        f"{result.messages_planned}"
    )
    print(
        f"Outbox jobs enqueued now: "
        f"{result.jobs_enqueued}"
    )
    print(
        "Outbox jobs already present: "
        f"{result.jobs_already_present}"
    )
    print(
        "Total durable outbox jobs: "
        f"{outbox_repository.count_jobs(SUPPLIER_CODE)}"
    )
    print()
    print(
        "REAL EXTERNAL NOTIFICATIONS SENT: 0"
    )
    print(
        "SHOPIFY WRITES PERFORMED: 0"
    )
    print(
        "SQLITE OUTBOX WRITES: "
        + (
            "ENABLED"
            if result.jobs_enqueued > 0
            else "0"
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
