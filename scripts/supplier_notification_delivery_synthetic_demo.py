from __future__ import annotations
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from supplier.orchestration.alert_repository import SupplierIncidentAlertRepository
from supplier.orchestration.notification_fake import FakeNotificationProvider
from supplier.orchestration.notification_models import NotificationChannel
from supplier.orchestration.notification_policy import build_notification_messages
from supplier.orchestration.notification_repository import SupplierNotificationDeliveryRepository
from supplier.orchestration.notification_service import SupplierNotificationDeliveryService


def main() -> int:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    @contextmanager
    def connection_factory():
        try:
            yield connection
        finally:
            connection.commit()

    alert_repository = SupplierIncidentAlertRepository(connection_factory=connection_factory)
    delivery_repository = SupplierNotificationDeliveryRepository(connection_factory=connection_factory)
    service = SupplierNotificationDeliveryService(alert_repository=alert_repository, delivery_repository=delivery_repository)

    critical_route = SimpleNamespace(
        route_event_id=1,
        incident_id="a" * 64,
        supplier_code="synthetic_delivery_supplier",
        source_event_type="incident_escalated",
        severity="critical",
        route="immediate_alert",
        policy_fingerprint="b" * 64,
        route_fingerprint="c" * 64,
        created_at="2026-11-22 12:00:00",
    )

    messages = build_notification_messages(alert_route=critical_route)
    provider = FakeNotificationProvider(fail_once_channels={NotificationChannel.WEBHOOK})

    print("SHOPIFY AUTOMATION LAB — V2.7 SYNTHETIC NOTIFICATION DELIVERY")
    print("=" * 72)
    print("DATABASE: IN-MEMORY ONLY")
    print("REAL EMAIL / SLACK / WEBHOOK DELIVERY: DISABLED")
    print("-" * 72)

    first = service.deliver_alert_route(alert_route=critical_route, provider=provider)
    print("FIRST DELIVERY")
    print(f"Messages planned: {first.messages_planned}")
    print(f"Attempted: {first.attempted}")
    print(f"Delivered: {first.delivered}")
    print(f"Failed: {first.failed}")
    print(f"Skipped: {first.skipped}")

    webhook_message = next(message for message in messages if message.channel == NotificationChannel.WEBHOOK)
    retry = service.retry_failed_message(message=webhook_message, provider=provider)
    print("-" * 72)
    print("EXPLICIT RETRY")
    print(f"Channel: {webhook_message.channel.value.upper()}")
    print(f"Attempt number: {retry.attempt_number}")
    print(f"Delivered: {retry.delivered}")

    second = service.deliver_alert_route(alert_route=critical_route, provider=provider)
    print("-" * 72)
    print("IDEMPOTENT RE-SCAN")
    print(f"Attempted: {second.attempted}")
    print(f"Delivered/already delivered: {second.delivered}")
    print(f"Skipped: {second.skipped}")

    print("-" * 72)
    print("SUMMARY")
    print(f"Provider unique delivered messages: {len(provider.messages)}")
    print(f"Persisted delivered receipts: {delivery_repository.count_delivered('synthetic_delivery_supplier')}")
    print(f"Persisted failed attempts: {delivery_repository.count_failed('synthetic_delivery_supplier')}")
    print("REAL EXTERNAL NOTIFICATIONS SENT: 0")
    print("REAL SQLITE DATABASE WRITES: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
