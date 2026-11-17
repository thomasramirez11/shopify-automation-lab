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


from supplier.batch.audit_repository import (  # noqa: E402
    SupplierBatchExecutionAuditRepository,
)


def main() -> int:
    repository = (
        SupplierBatchExecutionAuditRepository()
    )

    repository.ensure_schema()

    batch_ids = (
        repository.get_recent_batch_ids(
            limit=10
        )
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.6 BATCH EXECUTION AUDIT PREVIEW"
    )
    print("=" * 72)
    print(
        "LEDGER MODE: APPEND ONLY"
    )
    print(
        f"Batch events stored: "
        f"{repository.count_batch_events()}"
    )
    print(
        f"Item events stored: "
        f"{repository.count_item_events()}"
    )
    print("-" * 72)

    if not batch_ids:
        print(
            "No batch execution audit events stored yet."
        )
        return 0

    for batch_id in batch_ids:
        batch_events = (
            repository.get_batch_events(
                batch_id
            )
        )
        item_events = (
            repository.get_item_events(
                batch_id
            )
        )

        print(
            "BATCH"
        )
        print(
            batch_id
        )

        for event in batch_events:
            print(
                f"  {event.event_type.upper()} | "
                f"attempted={event.attempted_mutations} "
                f"applied={event.applied_mutations} "
                f"failed={event.failed_mutations}"
            )

        print(
            "  ITEMS"
        )

        for event in item_events:
            suffix = (
                f" | error={event.error_message}"
                if event.error_message
                else ""
            )

            print(
                f"    #{event.item_index} "
                f"{event.shopify_sku} | "
                f"{event.event_type.upper()} | "
                f"{event.before_quantity} -> "
                f"{event.requested_quantity}"
                f"{suffix}"
            )

        print("-" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
