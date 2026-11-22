from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from supplier.orchestration.alert_repository import SupplierIncidentAlertRepository
from supplier.orchestration.bootstrap import SUPPLIER_CODE
from supplier.orchestration.notification_fake import FakeNotificationProvider
from supplier.orchestration.notification_repository import SupplierNotificationDeliveryRepository
from supplier.orchestration.notification_service import SupplierNotificationDeliveryService


def main() -> int:
    alert_repository = SupplierIncidentAlertRepository()
    delivery_repository = SupplierNotificationDeliveryRepository()
    provider = FakeNotificationProvider()
    service = SupplierNotificationDeliveryService(alert_repository=alert_repository, delivery_repository=delivery_repository)
    result = service.deliver_existing_alert_routes(supplier_code=SUPPLIER_CODE, provider=provider, limit=100)

    print("SHOPIFY AUTOMATION LAB — V2.7 FAKE NOTIFICATION DELIVERY")
    print("=" * 72)
    print("PROVIDER: FAKE_NOTIFICATION_PROVIDER")
    print("REAL EMAIL / SLACK / WEBHOOK DELIVERY: DISABLED")
    print("LIVE SHOPIFY EXECUTION: DISABLED")
    print("-" * 72)
    print(f"Alert routes seen: {result.alert_routes_seen}")
    print(f"External messages planned: {result.external_messages_planned}")
    print(f"Provider attempts: {result.attempted}")
    print(f"Fake delivered: {result.delivered}")
    print(f"Fake failed: {result.failed}")
    print(f"Skipped/idempotent: {result.skipped}")
    print(f"Provider unique messages in memory: {len(provider.messages)}")
    print(f"Persisted delivered receipts: {delivery_repository.count_delivered(SUPPLIER_CODE)}")
    print(f"Persisted failed attempts: {delivery_repository.count_failed(SUPPLIER_CODE)}")
    print()
    print("REAL EXTERNAL NOTIFICATIONS SENT: 0")
    print("SHOPIFY WRITES PERFORMED: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
