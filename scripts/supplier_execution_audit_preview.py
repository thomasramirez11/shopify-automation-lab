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


from supplier.audit.repository import (  # noqa: E402
    SupplierExecutionAuditRepository,
)


def main() -> int:
    repository = (
        SupplierExecutionAuditRepository()
    )

    repository.ensure_schema()

    events = repository.get_recent(
        limit=20
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2 EXECUTION AUDIT LEDGER"
    )
    print("=" * 72)
    print(
        "LEDGER MODE: APPEND ONLY"
    )
    print(
        f"Events stored: "
        f"{repository.count_events()}"
    )
    print("-" * 72)

    if not events:
        print(
            "No V2 execution events stored yet."
        )
        print(
            "This is expected until the next controlled live execution."
        )
        return 0

    for event in events:
        print(
            f"Event #{event.event_id}"
        )
        print(
            f"Operation: {event.operation_id}"
        )
        print(
            f"Type: {event.event_type.upper()}"
        )
        print(
            f"Supplier SKU: {event.supplier_sku}"
        )
        print(
            f"Shopify SKU: {event.shopify_sku}"
        )
        print(
            f"Before: {event.before_quantity}"
        )
        print(
            f"Requested: {event.requested_quantity}"
        )
        print(
            "Observed after: "
            f"{event.observed_after_quantity}"
        )
        print(
            f"Recorded: {event.created_at}"
        )

        if event.error_message:
            print(
                f"Error: {event.error_message}"
            )

        print("-" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
