from __future__ import annotations

import argparse
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


from supplier.batch.approval import (  # noqa: E402
    evaluate_batch_approval,
)
from supplier.batch.audit_repository import (  # noqa: E402
    SupplierBatchExecutionAuditRepository,
)
from supplier.batch.audit_service import (  # noqa: E402
    SupplierBatchExecutionAuditService,
)
from supplier.batch.builder import (  # noqa: E402
    build_batch_safety_manifest,
)
from supplier.batch.fake_executor import (  # noqa: E402
    execute_approved_batch_fake,
)
from supplier.batch.models import (  # noqa: E402
    BatchSafetyPolicy,
)
from supplier.decision.models import (  # noqa: E402
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.execution.fake_adapter import (  # noqa: E402
    FakeInventoryMutationAdapter,
)
from supplier.plan.builder import (  # noqa: E402
    build_dry_run_sync_plan,
)


DEMO_POLICY = BatchSafetyPolicy(
    max_mutations_per_batch=5,
    max_total_absolute_inventory_delta=100,
    max_single_item_absolute_delta=50,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Execute the synthetic V2.6 fake batch and persist an "
            "append-only parent/child audit trail."
        )
    )

    parser.add_argument(
        "--approve-manifest",
        default=None,
        help="Exact batch manifest fingerprint.",
    )

    parser.add_argument(
        "--simulate-partial-failure",
        action="store_true",
        help=(
            "Make DEMO-SKU-B fail in the fake adapter so the audit "
            "ledger records a partial failure."
        ),
    )

    return parser.parse_args()


def build_demo_plan():
    return build_dry_run_sync_plan(
        [
            SupplierSyncDecision(
                supplier_code="demo_supplier",
                supplier_sku="DEMO-SUP-A",
                shopify_variant_id=(
                    "gid://shopify/ProductVariant/900001"
                ),
                shopify_sku="DEMO-SKU-A",
                status=(
                    SyncDecisionStatus.ELIGIBLE
                ),
                reason=(
                    SyncDecisionReason
                    .INVENTORY_MISMATCH_WITHIN_LIMIT
                ),
                current_inventory_quantity=10,
                supplier_inventory_quantity=15,
                inventory_delta=5,
                proposed_inventory_quantity=15,
            ),
            SupplierSyncDecision(
                supplier_code="demo_supplier",
                supplier_sku="DEMO-SUP-B",
                shopify_variant_id=(
                    "gid://shopify/ProductVariant/900002"
                ),
                shopify_sku="DEMO-SKU-B",
                status=(
                    SyncDecisionStatus.ELIGIBLE
                ),
                reason=(
                    SyncDecisionReason
                    .INVENTORY_MISMATCH_WITHIN_LIMIT
                ),
                current_inventory_quantity=20,
                supplier_inventory_quantity=32,
                inventory_delta=12,
                proposed_inventory_quantity=32,
            ),
        ]
    )


def main() -> int:
    args = parse_args()

    plan = build_demo_plan()

    manifest = build_batch_safety_manifest(
        plan=plan,
        policy=DEMO_POLICY,
    )

    approval = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            args.approve_manifest
        ),
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.6 BATCH EXECUTION AUDIT"
    )
    print("=" * 72)
    print(
        "MODE: SYNTHETIC / FAKE EXECUTION"
    )
    print(
        "LIVE SHOPIFY WRITES: DISABLED"
    )
    print("-" * 72)
    print(
        f"Manifest fingerprint:"
    )
    print(
        manifest.manifest_fingerprint
    )
    print(
        f"Approval status: "
        f"{approval.status.value.upper()}"
    )
    print(
        f"Execution authorized: "
        f"{approval.can_execute}"
    )

    if not approval.can_execute:
        print()
        print(
            "AUDIT EXECUTION NOT STARTED"
        )
        print(
            "SQLite audit writes: 0"
        )
        print(
            "Re-run with:"
        )
        print(
            "python scripts/"
            "supplier_batch_audit_fake_execution.py "
            "--approve-manifest "
            f"{manifest.manifest_fingerprint}"
        )
        return 0

    repository = (
        SupplierBatchExecutionAuditRepository()
    )
    service = (
        SupplierBatchExecutionAuditService(
            repository
        )
    )

    start = service.start_batch(
        plan=plan,
        manifest=manifest,
    )

    fail_variant_ids = (
        {
            "gid://shopify/ProductVariant/900002"
        }
        if args.simulate_partial_failure
        else set()
    )

    adapter = FakeInventoryMutationAdapter(
        fail_variant_ids=(
            fail_variant_ids
        )
    )

    execution = execute_approved_batch_fake(
        plan=plan,
        manifest=manifest,
        approval_report=approval,
        inventory_port=adapter,
    )

    completion = service.complete_batch(
        plan=plan,
        manifest=manifest,
        execution_report=(
            execution.execution_report
        ),
    )

    print("-" * 72)
    print(
        "BATCH AUDIT RESULT"
    )
    print("-" * 72)
    print(
        f"Batch ID:"
    )
    print(
        start.batch_id
    )
    print(
        f"Batch started event ID: "
        f"{start.batch_event_id}"
    )
    print(
        "Item started event IDs: "
        + ", ".join(
            str(event_id)
            for event_id
            in start.item_started_event_ids
        )
    )
    print(
        f"Terminal status: "
        f"{completion.terminal_event_type.value.upper()}"
    )
    print(
        f"Terminal event ID: "
        f"{completion.terminal_event_id}"
    )
    print(
        "Item result event IDs: "
        + ", ".join(
            str(event_id)
            for event_id
            in completion.item_result_event_ids
        )
    )
    print(
        f"Attempted fake mutations: "
        f"{execution.execution_report.attempted_mutations}"
    )
    print(
        f"Applied fake mutations: "
        f"{execution.execution_report.applied_mutations}"
    )
    print(
        f"Batch audit events stored: "
        f"{repository.count_batch_events()}"
    )
    print(
        f"Item audit events stored: "
        f"{repository.count_item_events()}"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )
    print(
        "SQLITE AUDIT WRITES: ENABLED"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
