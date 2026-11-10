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

if (
    str(PROJECT_ROOT)
    not in sys.path
):
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


from supplier.adapters.json_file_supplier import (  # noqa: E402
    JsonFileSupplierAdapter,
    SupplierFeedError,
)
from supplier.comparison.engine import (  # noqa: E402
    compare_supplier_to_shopify,
)
from supplier.comparison.snapshot import (  # noqa: E402
    SQLiteShopifyComparisonSnapshotAdapter,
    ShopifySnapshotError,
)
from supplier.decision.models import (  # noqa: E402
    InventorySyncPolicy,
)
from supplier.decision.policy import (  # noqa: E402
    evaluate_supplier_sync_decision,
)
from supplier.guard.guard import (  # noqa: E402
    evaluate_execution_guard,
)
from supplier.mapping.json_loader import (  # noqa: E402
    JsonSupplierMappingLoader,
    SupplierMappingFeedError,
)
from supplier.plan.builder import (  # noqa: E402
    build_dry_run_sync_plan,
)


SUPPLIER_CODE = "demo_supplier"
MAX_INVENTORY_DELTA = 50


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild the current V2 dry-run plan and verify an explicitly "
            "approved fingerprint."
        )
    )

    parser.add_argument(
        "--approve-fingerprint",
        default=None,
        help=(
            "Exact SHA-256 fingerprint from a previously reviewed dry-run "
            "plan. No Shopify writes are performed."
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

    mapping_loader = (
        JsonSupplierMappingLoader(
            mapping_feed_path
        )
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

    mapping_registry = (
        mapping_loader.load_registry()
    )

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
        "V2 EXECUTION GUARD PREVIEW"
    )
    print("=" * 68)

    try:
        plan = build_current_plan()

    except (
        SupplierFeedError,
        SupplierMappingFeedError,
        ShopifySnapshotError,
    ) as exc:
        print(
            "Guard status: INVALID_INPUT"
        )
        print(
            f"Reason: {exc}"
        )
        return 1

    report = (
        evaluate_execution_guard(
            plan=plan,
            approved_fingerprint=(
                args.approve_fingerprint
            ),
        )
    )

    print(
        "Current plan fingerprint:"
    )
    print(
        report.current_plan_fingerprint
    )
    print()

    if (
        report.approved_plan_fingerprint
        is not None
    ):
        print(
            "Approved fingerprint:"
        )
        print(
            report.approved_plan_fingerprint
        )
        print()

    print(
        f"Planned mutations: "
        f"{report.planned_mutations}"
    )
    print(
        f"Review items: "
        f"{report.review_items}"
    )
    print(
        f"Blocked items: "
        f"{report.blocked_items}"
    )
    print(
        f"Guard status: "
        f"{report.status.value.upper()}"
    )
    print(
        f"Execution authorized: "
        f"{report.can_execute}"
    )
    print(
        "EXECUTED MUTATIONS: 0"
    )
    print(
        "SHOPIFY WRITES PERFORMED: 0"
    )
    print(
        "SQLITE WRITES PERFORMED: 0"
    )

    if report.can_execute:
        print()
        print(
            "NOTE: READY means the plan passed the read-only guard. "
            "No executor exists in this checkpoint."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
