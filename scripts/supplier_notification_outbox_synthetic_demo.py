from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace


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
from supplier.orchestration.notification_fake import (  # noqa: E402
    FakeNotificationProvider,
)
from supplier.orchestration.notification_models import (  # noqa: E402
    NotificationChannel,
)
from supplier.orchestration.notification_repository import (  # noqa: E402
    SupplierNotificationDeliveryRepository,
)
from supplier.orchestration.notification_service import (  # noqa: E402
    SupplierNotificationDeliveryService,
)
from supplier.orchestration.outbox_models import (  # noqa: E402
    NotificationOutboxEventType,
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


SUPPLIER = "synthetic_outbox_supplier"


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

    alert_repository = (
        SupplierIncidentAlertRepository(
            connection_factory=(
                connection_factory
            )
        )
    )

    outbox_repository = (
        SupplierNotificationOutboxRepository(
            connection_factory=(
                connection_factory
            )
        )
    )

    delivery_repository = (
        SupplierNotificationDeliveryRepository(
            connection_factory=(
                connection_factory
            )
        )
    )

    delivery_service = (
        SupplierNotificationDeliveryService(
            alert_repository=(
                alert_repository
            ),
            delivery_repository=(
                delivery_repository
            ),
        )
    )

    outbox_service = (
        SupplierNotificationOutboxService(
            alert_repository=(
                alert_repository
            ),
            outbox_repository=(
                outbox_repository
            ),
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
            worker_id=(
                "synthetic-worker"
            ),
        )
    )

    critical_route = SimpleNamespace(
        route_event_id=1,
        incident_id="a" * 64,
        supplier_code=SUPPLIER,
        source_event_type=(
            "incident_escalated"
        ),
        severity="critical",
        route="immediate_alert",
        policy_fingerprint="b" * 64,
        route_fingerprint="c" * 64,
        created_at="2026-11-22 12:00:00",
    )

    enqueue = outbox_service.enqueue_alert_route(
        critical_route
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 SYNTHETIC DURABLE NOTIFICATION OUTBOX"
    )
    print("=" * 72)
    print(
        "DATABASE: IN-MEMORY ONLY"
    )
    print(
        "REAL EMAIL / SLACK / WEBHOOK DELIVERY: DISABLED"
    )
    print("-" * 72)

    print(
        "DURABLE ENQUEUE"
    )
    print(
        f"Messages planned: "
        f"{enqueue.messages_planned}"
    )
    print(
        f"Jobs enqueued: "
        f"{enqueue.jobs_enqueued}"
    )
    print(
        f"Jobs already present: "
        f"{enqueue.jobs_already_present}"
    )

    provider = FakeNotificationProvider(
        fail_once_channels={
            NotificationChannel.WEBHOOK
        }
    )

    first = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    print("-" * 72)
    print(
        "WORKER PASS #1"
    )
    print(
        f"Jobs seen: "
        f"{first.jobs_seen}"
    )
    print(
        f"Delivered: "
        f"{first.delivered}"
    )
    print(
        f"Failed: "
        f"{first.failed}"
    )

    recovery = outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=(
            provider.provider_name
        ),
    )

    second = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    print("-" * 72)
    print(
        "RECOVERY + WORKER PASS #2"
    )
    print(
        f"Retries queued: "
        f"{recovery.retries_queued}"
    )
    print(
        f"Delivered: "
        f"{second.delivered}"
    )
    print(
        f"Failed: "
        f"{second.failed}"
    )

    third = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    print("-" * 72)
    print(
        "IDEMPOTENT WORKER RE-SCAN"
    )
    print(
        f"Jobs seen: "
        f"{third.jobs_seen}"
    )
    print(
        f"Delivered: "
        f"{third.delivered}"
    )
    print(
        f"Failed: "
        f"{third.failed}"
    )

    # Crash/restart demonstration:
    crash_route = SimpleNamespace(
        route_event_id=2,
        incident_id="d" * 64,
        supplier_code=SUPPLIER,
        source_event_type=(
            "incident_opened"
        ),
        severity="warning",
        route="operator_review",
        policy_fingerprint="e" * 64,
        route_fingerprint="f" * 64,
        created_at="2026-11-22 12:05:00",
    )

    crash_enqueue = (
        outbox_service.enqueue_alert_route(
            crash_route
        )
    )

    crash_job = (
        outbox_repository.get_pending_jobs(
            supplier_code=SUPPLIER,
            limit=100,
        )[0]
    )

    outbox_repository.append_event(
        message=crash_job.message,
        event_type=(
            NotificationOutboxEventType
            .CLAIMED.value
        ),
        attempt_number=1,
        worker_id="crashed-worker",
        provider_name=(
            provider.provider_name
        ),
    )

    # Provider accepted the message, then the process "crashes" before the
    # delivery/outbox success audit is written.
    provider.send(
        crash_job.message
    )

    resumed = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    print("-" * 72)
    print(
        "CRASH / RESTART RECOVERY"
    )
    print(
        f"Crash-demo jobs enqueued: "
        f"{crash_enqueue.jobs_enqueued}"
    )
    print(
        f"Interrupted jobs resumed: "
        f"{resumed.jobs_resumed}"
    )
    print(
        f"Delivered after restart: "
        f"{resumed.delivered}"
    )
    print(
        f"Provider unique delivered messages total: "
        f"{len(provider.messages)}"
    )

    print("-" * 72)
    print(
        "FINAL OUTBOX STATE"
    )
    print(
        "Delivered jobs: "
        f"{outbox_repository.count_state(supplier_code=SUPPLIER, state=NotificationOutboxState.DELIVERED)}"
    )
    print(
        "Failed jobs: "
        f"{outbox_repository.count_state(supplier_code=SUPPLIER, state=NotificationOutboxState.FAILED)}"
    )
    print(
        "Dead-lettered jobs: "
        f"{outbox_repository.count_state(supplier_code=SUPPLIER, state=NotificationOutboxState.DEAD_LETTERED)}"
    )
    print(
        "REAL EXTERNAL NOTIFICATIONS SENT: 0"
    )
    print(
        "REAL SQLITE DATABASE WRITES: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
