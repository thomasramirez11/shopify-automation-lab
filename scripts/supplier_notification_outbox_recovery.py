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
from supplier.orchestration.outbox_service import (  # noqa: E402
    SupplierNotificationOutboxService,
)
from supplier.orchestration.outbox_worker import (  # noqa: E402
    SupplierNotificationOutboxWorker,
)


def main() -> int:
    provider = (
        FakeNotificationProvider()
    )

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

    outbox_service = (
        SupplierNotificationOutboxService(
            alert_repository=(
                SupplierIncidentAlertRepository()
            ),
            outbox_repository=(
                outbox_repository
            ),
        )
    )

    recovery = (
        outbox_service.recover_failed_jobs(
            supplier_code=(
                SUPPLIER_CODE
            ),
            provider_name=(
                provider.provider_name
            ),
            limit=100,
        )
    )

    worker = (
        SupplierNotificationOutboxWorker(
            outbox_repository=(
                outbox_repository
            ),
            delivery_service=(
                delivery_service
            ),
        )
    )

    worker_result = worker.process_pending(
        supplier_code=SUPPLIER_CODE,
        provider=provider,
        limit=100,
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 NOTIFICATION OUTBOX RECOVERY"
    )
    print("=" * 72)
    print(
        "PROVIDER: FAKE_NOTIFICATION_PROVIDER"
    )
    print(
        "REAL EXTERNAL DELIVERY: DISABLED"
    )
    print("-" * 72)

    print(
        "RECOVERY QUEUE"
    )
    print(
        f"Failed jobs seen: "
        f"{recovery.failed_jobs_seen}"
    )
    print(
        f"Retries queued: "
        f"{recovery.retries_queued}"
    )
    print(
        f"Dead-lettered: "
        f"{recovery.dead_lettered}"
    )
    print(
        "Already recovered: "
        f"{recovery.already_recovered}"
    )
    print("-" * 72)

    print(
        "WORKER RESULT"
    )
    print(
        f"Jobs seen: "
        f"{worker_result.jobs_seen}"
    )
    print(
        f"Delivered: "
        f"{worker_result.delivered}"
    )
    print(
        f"Failed: "
        f"{worker_result.failed}"
    )
    print(
        "Dead-letter jobs now: "
        f"{outbox_repository.count_state(supplier_code=SUPPLIER_CODE, state=NotificationOutboxState.DEAD_LETTERED)}"
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
