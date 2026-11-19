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


from supplier.adapters.json_file_supplier import (  # noqa: E402
    JsonFileSupplierAdapter,
)
from supplier.batch.models import BatchSafetyPolicy  # noqa: E402
from supplier.comparison.snapshot import (  # noqa: E402
    SQLiteShopifyComparisonSnapshotAdapter,
)
from supplier.decision.models import InventorySyncPolicy  # noqa: E402
from supplier.mapping.json_loader import (  # noqa: E402
    JsonSupplierMappingLoader,
)
from supplier.orchestration.backlog import (  # noqa: E402
    SQLiteSupplierOperationsBacklogReader,
)
from supplier.orchestration.orchestrator import (  # noqa: E402
    SupplierOperationsOrchestrator,
)


SUPPLIER_CODE = "demo_supplier"

ITEM_POLICY = InventorySyncPolicy(
    max_inventory_delta=50
)

BATCH_POLICY = BatchSafetyPolicy(
    max_mutations_per_batch=5,
    max_total_absolute_inventory_delta=100,
    max_single_item_absolute_delta=50,
)


def main() -> int:
    supplier_feed_path = (
        PROJECT_ROOT
        / "supplier"
        / "samples"
        / "sample_supplier_feed.json"
    )

    mapping_feed_path = (
        PROJECT_ROOT
        / "supplier"
        / "samples"
        / "sample_supplier_mappings.json"
    )

    orchestrator = SupplierOperationsOrchestrator(
        supplier_code=SUPPLIER_CODE,
        supplier_adapter=(
            JsonFileSupplierAdapter(
                supplier_feed_path
            )
        ),
        mapping_loader=(
            JsonSupplierMappingLoader(
                mapping_feed_path
            )
        ),
        snapshot_adapter=(
            SQLiteShopifyComparisonSnapshotAdapter()
        ),
        item_policy=ITEM_POLICY,
        batch_policy=BATCH_POLICY,
        backlog_reader=(
            SQLiteSupplierOperationsBacklogReader()
        ),
    )

    snapshot = orchestrator.build_snapshot()

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 UNIFIED SUPPLIER OPERATIONS ORCHESTRATOR"
    )
    print("=" * 72)
    print(
        "MODE: READ ONLY CONTROL PLANE"
    )
    print(
        "LIVE SHOPIFY EXECUTION: DISABLED"
    )
    print(
        "SQLITE BUSINESS WRITES: 0"
    )
    print("-" * 72)

    print(
        "SUPPLIER PIPELINE"
    )
    print("-" * 72)
    print(
        f"Supplier: "
        f"{snapshot.supplier_code}"
    )
    print(
        f"Supplier products: "
        f"{snapshot.supplier_product_count}"
    )
    print(
        f"Active mappings: "
        f"{snapshot.active_mapping_count}"
    )
    print(
        f"Decisions: "
        f"{snapshot.decision_count}"
    )
    print(
        f"Planned mutations: "
        f"{snapshot.plan.planned_mutations}"
    )
    print(
        f"Review items: "
        f"{snapshot.plan.review_items}"
    )
    print(
        f"Blocked items: "
        f"{snapshot.plan.blocked_items}"
    )
    print(
        f"No-action items: "
        f"{snapshot.plan.no_action_items}"
    )
    print("-" * 72)

    print(
        "BATCH SAFETY"
    )
    print("-" * 72)
    print(
        f"Manifest status: "
        f"{snapshot.manifest.status.value.upper()}"
    )
    print(
        "Manifest reasons: "
        + ", ".join(
            reason.value
            for reason
            in snapshot.manifest.reasons
        )
    )
    print(
        "Total absolute inventory delta: "
        f"{snapshot.manifest.total_absolute_inventory_delta}"
    )
    print(
        "Manifest fingerprint:"
    )
    print(
        snapshot.manifest.manifest_fingerprint
    )
    print("-" * 72)

    print(
        "OPERATIONS BACKLOG"
    )
    print("-" * 72)
    print(
        "Queued retry attempts: "
        f"{snapshot.backlog.queued_retry_attempts}"
    )
    print(
        "DLQ awaiting human: "
        f"{snapshot.backlog.dead_letter_awaiting_human}"
    )
    print(
        "DLQ acknowledged/unresolved: "
        f"{snapshot.backlog.dead_letter_acknowledged}"
    )
    print(
        "Resolution recorded: "
        f"{snapshot.backlog.resolution_recorded}"
    )
    print(
        "Re-entry authorized: "
        f"{snapshot.backlog.reentry_authorized}"
    )
    print(
        "Re-entry started/unclosed: "
        f"{snapshot.backlog.reentry_started}"
    )
    print(
        "Re-entry failed: "
        f"{snapshot.backlog.reentry_failed}"
    )
    print(
        "Closed resolutions: "
        f"{snapshot.backlog.resolution_closed}"
    )
    print("-" * 72)

    print(
        "CONTROL PLANE DECISION"
    )
    print("-" * 72)
    print(
        f"SYSTEM POSTURE: "
        f"{snapshot.posture.value.upper()}"
    )
    print(
        f"NEXT ALLOWED ACTION: "
        f"{snapshot.next_action.value.upper()}"
    )
    print(
        "Orchestration snapshot fingerprint:"
    )
    print(
        snapshot.orchestration_fingerprint
    )
    print("-" * 72)

    guidance = {
        "review_dead_letter_cases": (
            "Review unresolved DLQ/case-resolution work before "
            "starting a new supplier batch."
        ),
        "process_retry_queue": (
            "Process isolated retry work before approving "
            "new supplier mutations."
        ),
        "approve_batch": (
            "A safe mutation batch exists and is ready "
            "for explicit approval."
        ),
        "review_batch": (
            "The supplier batch requires human review "
            "before execution can be considered."
        ),
        "fix_blocking_issues": (
            "Hard safety issues block supplier execution."
        ),
        "none": (
            "No supplier mutation or recovery action "
            "is currently required."
        ),
    }

    print(
        "Operator guidance:"
    )
    print(
        guidance[
            snapshot.next_action.value
        ]
    )
    print()
    print(
        "SHOPIFY WRITES PERFORMED: 0"
    )
    print(
        "SQLITE WRITES PERFORMED: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
