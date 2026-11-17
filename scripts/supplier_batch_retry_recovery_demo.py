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
from supplier.batch.retry_models import (  # noqa: E402
    RetryPolicy,
)
from supplier.batch.retry_repository import (  # noqa: E402
    SupplierBatchRetryRepository,
)
from supplier.batch.retry_service import (  # noqa: E402
    SupplierBatchRetryService,
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


VARIANT_A = "gid://shopify/ProductVariant/910001"
VARIANT_B = "gid://shopify/ProductVariant/910002"


def build_recovery_demo_plan():
    return build_dry_run_sync_plan(
        [
            SupplierSyncDecision(
                supplier_code="demo_supplier",
                supplier_sku="RETRY-SUP-A",
                shopify_variant_id=VARIANT_A,
                shopify_sku="RETRY-DEMO-A",
                status=SyncDecisionStatus.ELIGIBLE,
                reason=(
                    SyncDecisionReason
                    .INVENTORY_MISMATCH_WITHIN_LIMIT
                ),
                current_inventory_quantity=5,
                supplier_inventory_quantity=8,
                inventory_delta=3,
                proposed_inventory_quantity=8,
            ),
            SupplierSyncDecision(
                supplier_code="demo_supplier",
                supplier_sku="RETRY-SUP-B",
                shopify_variant_id=VARIANT_B,
                shopify_sku="RETRY-DEMO-B",
                status=SyncDecisionStatus.ELIGIBLE,
                reason=(
                    SyncDecisionReason
                    .INVENTORY_MISMATCH_WITHIN_LIMIT
                ),
                current_inventory_quantity=7,
                supplier_inventory_quantity=11,
                inventory_delta=4,
                proposed_inventory_quantity=11,
            ),
        ]
    )


def main() -> int:
    plan = build_recovery_demo_plan()

    manifest = build_batch_safety_manifest(
        plan=plan,
        policy=BatchSafetyPolicy(
            max_mutations_per_batch=5,
            max_total_absolute_inventory_delta=100,
            max_single_item_absolute_delta=50,
        ),
    )

    approval = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            manifest.manifest_fingerprint
        ),
    )

    batch_repository = (
        SupplierBatchExecutionAuditRepository()
    )
    batch_audit = (
        SupplierBatchExecutionAuditService(
            batch_repository
        )
    )

    start = batch_audit.start_batch(
        plan=plan,
        manifest=manifest,
    )

    partial_adapter = (
        FakeInventoryMutationAdapter(
            fail_variant_ids={
                VARIANT_B
            }
        )
    )

    initial_execution = (
        execute_approved_batch_fake(
            plan=plan,
            manifest=manifest,
            approval_report=approval,
            inventory_port=(
                partial_adapter
            ),
        )
    )

    completion = batch_audit.complete_batch(
        plan=plan,
        manifest=manifest,
        execution_report=(
            initial_execution.execution_report
        ),
    )

    retry_repository = (
        SupplierBatchRetryRepository()
    )

    retry_service = (
        SupplierBatchRetryService(
            repository=(
                retry_repository
            ),
            policy=RetryPolicy(
                max_attempts_per_item=3
            ),
        )
    )

    queue_summary = (
        retry_service
        .queue_eligible_failures()
    )

    recovery_adapter = (
        FakeInventoryMutationAdapter()
    )

    retry_summary = (
        retry_service
        .execute_queued_retries(
            inventory_port=(
                recovery_adapter
            )
        )
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.6 RETRY + RECOVERY DEMO"
    )
    print("=" * 72)
    print(
        "MODE: SYNTHETIC / NON-LIVE"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )
    print("-" * 72)

    print(
        "INITIAL BATCH"
    )
    print("-" * 72)
    print(
        f"Batch ID:"
    )
    print(
        start.batch_id
    )
    print(
        f"Terminal status: "
        f"{completion.terminal_event_type.value.upper()}"
    )
    print(
        "Initial attempted mutations: "
        f"{initial_execution.execution_report.attempted_mutations}"
    )
    print(
        "Initial applied mutations: "
        f"{initial_execution.execution_report.applied_mutations}"
    )
    print(
        "Initial failed mutations: "
        f"{initial_execution.execution_report.attempted_mutations - initial_execution.execution_report.applied_mutations}"
    )
    print("-" * 72)

    print(
        "RETRY QUEUE"
    )
    print("-" * 72)
    print(
        f"Failed items seen: "
        f"{queue_summary.failed_items_seen}"
    )
    print(
        f"Queued for retry: "
        f"{queue_summary.queued}"
    )
    print(
        f"Already recovered: "
        f"{queue_summary.already_recovered}"
    )
    print(
        f"Exhausted: "
        f"{queue_summary.exhausted}"
    )
    print(
        f"Non-retryable: "
        f"{queue_summary.non_retryable}"
    )
    print("-" * 72)

    print(
        "RECOVERY EXECUTION"
    )
    print("-" * 72)
    print(
        f"Queued retries seen: "
        f"{retry_summary.queued_retries_seen}"
    )
    print(
        f"Retry attempted: "
        f"{retry_summary.attempted}"
    )
    print(
        f"Retry succeeded: "
        f"{retry_summary.succeeded}"
    )
    print(
        f"Retry failed: "
        f"{retry_summary.failed}"
    )
    print(
        f"Retry exhausted now: "
        f"{retry_summary.exhausted_now}"
    )

    print(
        "Recovered fake mutations:"
    )

    for mutation in recovery_adapter.mutations:
        print(
            f"  {mutation.shopify_sku} "
            f"-> {mutation.inventory_quantity}"
        )

    print("-" * 72)
    print(
        f"Retry ledger events stored: "
        f"{retry_repository.count_events()}"
    )
    print(
        "Successful original item retried: "
        f"{any(m.shopify_sku == 'RETRY-DEMO-A' for m in recovery_adapter.mutations)}"
    )
    print(
        "Failed original item retried: "
        f"{any(m.shopify_sku == 'RETRY-DEMO-B' for m in recovery_adapter.mutations)}"
    )
    print(
        "SQLITE AUDIT WRITES: ENABLED"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
