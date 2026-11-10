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


from supplier.adapters.json_file_supplier import (  # noqa: E402
    JsonFileSupplierAdapter,
)
from supplier.comparison.engine import (  # noqa: E402
    compare_supplier_to_shopify,
)
from supplier.comparison.snapshot import (  # noqa: E402
    SQLiteShopifyComparisonSnapshotAdapter,
)
from supplier.decision.models import (  # noqa: E402
    InventorySyncPolicy,
)
from supplier.decision.policy import (  # noqa: E402
    evaluate_supplier_sync_decision,
)
from supplier.execution.executor import (  # noqa: E402
    execute_sync_plan,
)
from supplier.execution.fake_adapter import (  # noqa: E402
    FakeInventoryMutationAdapter,
)
from supplier.guard.guard import (  # noqa: E402
    evaluate_execution_guard,
)
from supplier.mapping.json_loader import (  # noqa: E402
    JsonSupplierMappingLoader,
)
from supplier.plan.builder import (  # noqa: E402
    build_dry_run_sync_plan,
)


SUPPLIER_CODE = "demo_supplier"
MAX_INVENTORY_DELTA = 50


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Execute the current approved supplier sync plan against an "
            "in-memory fake Shopify inventory adapter."
        )
    )

    parser.add_argument(
        "--approve-fingerprint",
        required=True,
        help=(
            "Exact SHA-256 fingerprint from the reviewed current plan."
        ),
    )

    return parser.parse_args()


def build_current_plan():
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

    supplier_adapter = (
        JsonFileSupplierAdapter(
            supplier_feed_path
        )
    )

    mapping_registry = (
        JsonSupplierMappingLoader(
            mapping_feed_path
        )
        .load_registry()
    )

    snapshot_adapter = (
        SQLiteShopifyComparisonSnapshotAdapter()
    )

    policy = InventorySyncPolicy(
        max_inventory_delta=(
            MAX_INVENTORY_DELTA
        )
    )

    supplier_products = {
        product.supplier_sku: product
        for product
        in supplier_adapter.list_products()
    }

    decisions = []

    for mapping in (
        mapping_registry.list_mappings(
            active_only=True
        )
    ):
        if (
            mapping.supplier_code
            != SUPPLIER_CODE
        ):
            continue

        supplier_product = (
            supplier_products.get(
                mapping.supplier_sku
            )
        )

        snapshot = (
            snapshot_adapter.get_snapshot(
                mapping.shopify_variant_id
            )
        )

        comparison = (
            compare_supplier_to_shopify(
                mapping=mapping,
                supplier_product=(
                    supplier_product
                ),
                shopify_variant=(
                    snapshot.shopify_variant
                    if snapshot
                    is not None
                    else None
                ),
                stored_cost=(
                    snapshot.stored_cost
                    if snapshot
                    is not None
                    else None
                ),
            )
        )

        decisions.append(
            evaluate_supplier_sync_decision(
                comparison=comparison,
                policy=policy,
            )
        )

    return build_dry_run_sync_plan(
        decisions
    )


def main() -> int:
    args = parse_args()

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2 FAKE INVENTORY EXECUTION"
    )
    print("=" * 68)

    plan = build_current_plan()

    guard = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            args.approve_fingerprint
        ),
    )

    print(
        f"Current fingerprint: "
        f"{plan.fingerprint}"
    )
    print(
        f"Guard status: "
        f"{guard.status.value.upper()}"
    )
    print(
        f"Execution authorized: "
        f"{guard.can_execute}"
    )
    print("-" * 68)

    if not guard.can_execute:
        print(
            "FAKE EXECUTION ABORTED."
        )
        print(
            "FAKE MUTATIONS APPLIED: 0"
        )
        print(
            "LIVE SHOPIFY WRITES: 0"
        )
        return 1

    fake_adapter = (
        FakeInventoryMutationAdapter()
    )

    report = execute_sync_plan(
        plan=plan,
        guard_report=guard,
        inventory_port=fake_adapter,
    )

    for number, mutation in enumerate(
        fake_adapter.mutations,
        start=1,
    ):
        print(
            f"FAKE MUTATION #{number}"
        )
        print(
            f"Shopify SKU: "
            f"{mutation.shopify_sku}"
        )
        print(
            f"Variant: "
            f"{mutation.shopify_variant_id}"
        )
        print(
            "Set inventory to: "
            f"{mutation.inventory_quantity}"
        )
        print("-" * 68)

    print(
        f"Attempted fake mutations: "
        f"{report.attempted_mutations}"
    )
    print(
        f"Applied fake mutations: "
        f"{report.applied_mutations}"
    )
    print(
        f"Execution report success: "
        f"{report.succeeded}"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )
    print(
        "SQLITE WRITES: 0"
    )

    return (
        0
        if report.succeeded
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
