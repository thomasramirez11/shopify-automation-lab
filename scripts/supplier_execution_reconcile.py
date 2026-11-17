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


from supplier.reconciliation.repository import (  # noqa: E402
    SupplierExecutionReconciliationRepository,
)
from supplier.reconciliation.service import (  # noqa: E402
    SupplierExecutionReconciliationService,
)


def main() -> int:
    repository = (
        SupplierExecutionReconciliationRepository()
    )

    service = (
        SupplierExecutionReconciliationService(
            repository
        )
    )

    summary = service.reconcile_all()

    recent = repository.get_recent(
        limit=10
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2 EXECUTION RECONCILIATION"
    )
    print("=" * 72)
    print(
        "SOURCE OF TRUTH A: V2 verified execution ledger"
    )
    print(
        "SOURCE OF TRUTH B: V1 post-execution Shopify sync"
    )
    print("-" * 72)

    print(
        "Verified operations seen: "
        f"{summary.verified_operations_seen}"
    )
    print(
        "Already reconciled MATCH: "
        f"{summary.already_matched}"
    )
    print(
        "Waiting for newer V1 sync: "
        f"{summary.waiting_for_new_v1_sync}"
    )
    print(
        "Reconciliations written now: "
        f"{summary.reconciliations_written}"
    )
    print(
        "MATCH written: "
        f"{summary.matches_written}"
    )
    print(
        "MISMATCH written: "
        f"{summary.mismatches_written}"
    )
    print(
        "VARIANT_MISSING written: "
        f"{summary.missing_variants_written}"
    )
    print(
        "Total reconciliation events: "
        f"{repository.count_events()}"
    )
    print("-" * 72)

    if not recent:
        print(
            "No reconciliation events stored yet."
        )
        print(
            "A verified V2 execution plus a newer successful V1 sync "
            "is required."
        )
        return 0

    print(
        "RECENT RECONCILIATION EVENTS"
    )
    print("-" * 72)

    for event in recent:
        print(
            f"Reconciliation #{event.reconciliation_id}"
        )
        print(
            f"Operation: {event.operation_id}"
        )
        print(
            f"V1 sync run: #{event.sync_run_id}"
        )
        print(
            f"Shopify SKU: {event.shopify_sku}"
        )
        print(
            f"Expected: {event.expected_quantity}"
        )
        print(
            "Observed in SQLite: "
            f"{event.observed_sqlite_quantity}"
        )
        print(
            f"Status: {event.status.upper()}"
        )
        print(
            f"Recorded: {event.created_at}"
        )
        print("-" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
