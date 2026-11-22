from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from supplier.orchestration.bootstrap import SUPPLIER_CODE
from supplier.orchestration.notification_repository import SupplierNotificationDeliveryRepository


def main() -> int:
    repository = SupplierNotificationDeliveryRepository()
    repository.ensure_schema()
    events = repository.get_recent_events(supplier_code=SUPPLIER_CODE, limit=100)

    print("SHOPIFY AUTOMATION LAB — V2.7 NOTIFICATION DELIVERY HISTORY")
    print("=" * 72)
    print("LEDGER MODE: APPEND ONLY")
    print("REAL EXTERNAL DELIVERY: DISABLED")
    print(f"Supplier: {SUPPLIER_CODE}")
    print(f"Delivered receipts: {repository.count_delivered(SUPPLIER_CODE)}")
    print(f"Failed attempts: {repository.count_failed(SUPPLIER_CODE)}")
    print("-" * 72)

    if not events:
        print("No notification delivery events recorded.")
        return 0

    for event in events:
        print(f"Delivery event #{event.delivery_event_id}")
        print(f"  Channel: {event.channel.upper()}")
        print(f"  Event: {event.event_type.upper()}")
        print(f"  Attempt: {event.attempt_number}")
        print(f"  Provider: {event.provider_name}")
        if event.provider_message_id:
            print(f"  Provider message: {event.provider_message_id}")
        if event.error_message:
            print(f"  Error: {event.error_message}")
        print("-" * 72)

    print("REAL EXTERNAL NOTIFICATIONS SENT: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
