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
from supplier.orchestration.notification_fake import (  # noqa: E402
    FakeNotificationProvider,
)
from supplier.orchestration.notification_repository import (  # noqa: E402
    SupplierNotificationDeliveryRepository,
)
from supplier.orchestration.notification_service import (  # noqa: E402
    SupplierNotificationDeliveryService,
)
from supplier.orchestration.outbox_models import (  # noqa: E402
    NotificationOutboxState,
)
from supplier.orchestration.outbox_repository import (  # noqa: E402
    SupplierNotificationOutboxRepository,
)
from supplier.orchestration.outbox_worker import (  # noqa: E402
    SupplierNotificationOutboxWorker,
)


def main() -> int:
    outbox_repository = (
        SupplierNotificationOutboxRepository()
    )

    delivery_service = (
        SupplierNotificationDeliveryService(
            alert_repository=(
                SupplierIncidentAlertRepository()
            ),
            delivery_repository=(
                SupplierNotificationDeliveryRepository()
            ),
        )
    )

    worker = SupplierNotificationOutboxWorker(
        outbox_repository=(
            outbox_repository
        ),
        delivery_service=(
            delivery_service
        ),
    )

    provider = (
        FakeNotificationProvider()
    )

    result = worker.process_pending(
        supplier_code=SUPPLIER_CODE,
        provider=provider,
        limit=100,
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 DURABLE NOTIFICATION OUTBOX WORKER"
    )
    print("=" * 72)
    print(
        "PROVIDER: FAKE_NOTIFICATION_PROVIDER"
    )
    print(
        "REAL EMAIL / SLACK / WEBHOOK DELIVERY: DISABLED"
    )
    print("-" * 72)

    print(
        f"Pending jobs seen: "
        f"{result.jobs_seen}"
    )
    print(
        f"Jobs claimed now: "
        f"{result.jobs_claimed}"
    )
    print(
        f"Interrupted jobs resumed: "
        f"{result.jobs_resumed}"
    )
    print(
        f"Delivered: "
        f"{result.delivered}"
    )
    print(
        f"Failed: "
        f"{result.failed}"
    )
    print(
        f"Skipped: "
        f"{result.skipped}"
    )
    print(
        "Outbox delivered jobs: "
        f"{outbox_repository.count_state(supplier_code=SUPPLIER_CODE, state=NotificationOutboxState.DELIVERED)}"
    )
    print(
        "Outbox failed jobs: "
        f"{outbox_repository.count_state(supplier_code=SUPPLIER_CODE, state=NotificationOutboxState.FAILED)}"
    )
    print()
    print(
        "REAL EXTERNAL NOTIFICATIONS SENT: 0"
    )
    print(
        "SHOPIFY WRITES PERFORMED: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
