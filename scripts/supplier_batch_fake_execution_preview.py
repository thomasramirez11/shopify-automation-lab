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
            "Preview and optionally approve a synthetic two-item "
            "V2.6 fake batch. No Shopify or SQLite access is used."
        )
    )

    parser.add_argument(
        "--approve-manifest",
        default=None,
        help=(
            "Exact batch manifest fingerprint printed during PREPARE."
        ),
    )

    return parser.parse_args()


def build_demo_plan():
    """
    Synthetic batch only.

    We deliberately do NOT use the real cap/shirt state because they now
    match the supplier feed and should remain untouched.
    """

    decisions = [
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

    return build_dry_run_sync_plan(
        decisions
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
        "V2.6 BATCH APPROVAL + FAKE EXECUTION"
    )
    print("=" * 72)
    print(
        "MODE: SYNTHETIC / NON-LIVE"
    )
    print(
        "SHOPIFY ACCESS: NONE"
    )
    print(
        "SQLITE ACCESS: NONE"
    )
    print("-" * 72)

    print(
        "BATCH SAFETY"
    )
    print("-" * 72)
    print(
        f"Status: "
        f"{manifest.status.value.upper()}"
    )
    print(
        f"Planned mutations: "
        f"{manifest.planned_mutations}"
    )
    print(
        "Total absolute inventory delta: "
        f"{manifest.total_absolute_inventory_delta}"
    )
    print(
        "Largest single-item absolute delta: "
        f"{manifest.largest_single_item_absolute_delta}"
    )
    print()

    for index, item in enumerate(
        manifest.mutations,
        start=1,
    ):
        print(
            f"Mutation #{index}: "
            f"{item.shopify_sku} | "
            f"{item.current_inventory_quantity} "
            f"-> "
            f"{item.proposed_inventory_quantity} "
            f"(delta {item.inventory_delta:+d})"
        )

    print("-" * 72)
    print(
        "Source plan fingerprint:"
    )
    print(
        manifest.source_plan_fingerprint
    )
    print(
        "Batch manifest fingerprint:"
    )
    print(
        manifest.manifest_fingerprint
    )
    print("-" * 72)

    print(
        "BATCH APPROVAL"
    )
    print("-" * 72)
    print(
        f"Status: "
        f"{approval.status.value.upper()}"
    )
    print(
        f"Execution authorized: "
        f"{approval.can_execute}"
    )

    if not approval.can_execute:
        print()
        print(
            "PREPARE STATUS: APPROVAL REQUIRED"
        )
        print(
            "Re-run with:"
        )
        print(
            "python scripts/"
            "supplier_batch_fake_execution_preview.py "
            "--approve-manifest "
            f"{manifest.manifest_fingerprint}"
        )
        print()
        print(
            "FAKE MUTATIONS EXECUTED: 0"
        )
        print(
            "LIVE SHOPIFY WRITES: 0"
        )
        print(
            "SQLITE WRITES: 0"
        )
        return 0

    adapter = (
        FakeInventoryMutationAdapter()
    )

    result = execute_approved_batch_fake(
        plan=plan,
        manifest=manifest,
        approval_report=approval,
        inventory_port=adapter,
    )

    print()
    print(
        "FAKE BATCH EXECUTION"
    )
    print("-" * 72)

    for index, mutation_result in enumerate(
        result.execution_report.results,
        start=1,
    ):
        print(
            f"Result #{index}: "
            f"{mutation_result.shopify_sku} "
            f"-> "
            f"{mutation_result.requested_inventory_quantity} "
            f"| applied={mutation_result.applied}"
        )

    print("-" * 72)
    print(
        f"Attempted fake mutations: "
        f"{result.execution_report.attempted_mutations}"
    )
    print(
        f"Applied fake mutations: "
        f"{result.execution_report.applied_mutations}"
    )
    print(
        f"Batch execution success: "
        f"{result.succeeded}"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )
    print(
        "SQLITE WRITES: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
