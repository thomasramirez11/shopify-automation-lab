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
from supplier.orchestration.outbox_models import (  # noqa: E402
    NotificationOutboxState,
)
from supplier.orchestration.outbox_repository import (  # noqa: E402
    SupplierNotificationOutboxRepository,
)


def main() -> int:
    repository = (
        SupplierNotificationOutboxRepository()
    )

    repository.ensure_schema()

    events = repository.get_recent_events(
        supplier_code=SUPPLIER_CODE,
        limit=100,
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 DURABLE NOTIFICATION OUTBOX HISTORY"
    )
    print("=" * 72)
    print(
        "LEDGER MODE: APPEND ONLY"
    )
    print(
        f"Supplier: {SUPPLIER_CODE}"
    )
    print(
        f"Durable jobs: "
        f"{repository.count_jobs(SUPPLIER_CODE)}"
    )

    for state in (
        NotificationOutboxState.ENQUEUED,
        NotificationOutboxState.CLAIMED,
        NotificationOutboxState.RETRY_QUEUED,
        NotificationOutboxState.FAILED,
        NotificationOutboxState.DELIVERED,
        NotificationOutboxState.DEAD_LETTERED,
    ):
        print(
            f"{state.value}: "
            f"{repository.count_state(supplier_code=SUPPLIER_CODE, state=state)}"
        )

    print("-" * 72)

    if not events:
        print(
            "No notification outbox events recorded."
        )
        return 0

    for event in events:
        print(
            f"Outbox event #{event.outbox_event_id}"
        )
        print(
            f"  Delivery: "
            f"{event.delivery_id}"
        )
        print(
            f"  Channel: "
            f"{event.channel.upper()}"
        )
        print(
            f"  Event: "
            f"{event.event_type.upper()}"
        )
        print(
            f"  Attempt: "
            f"{event.attempt_number}"
        )

        if event.worker_id:
            print(
                f"  Worker: "
                f"{event.worker_id}"
            )

        if event.error_message:
            print(
                f"  Error: "
                f"{event.error_message}"
            )

        print("-" * 72)

    print()
    print(
        "REAL EXTERNAL NOTIFICATIONS SENT: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
