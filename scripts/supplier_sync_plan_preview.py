from __future__ import annotations

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
from supplier.mapping.json_loader import (  # noqa: E402
    JsonSupplierMappingLoader,
    SupplierMappingFeedError,
)
from supplier.plan.builder import (  # noqa: E402
    build_dry_run_sync_plan,
)


SUPPLIER_CODE = "demo_supplier"
MAX_INVENTORY_DELTA = 50


def main() -> int:
    """
    Build a complete dry-run supplier synchronization plan.

    This command performs no Shopify or SQLite writes.
    """

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

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2 DRY-RUN SYNC PLAN"
    )
    print("=" * 64)

    try:
        supplier_products = {
            product.supplier_sku: product
            for product
            in supplier_adapter.list_products()
        }

        mapping_registry = (
            mapping_loader.load_registry()
        )

        active_mappings = tuple(
            mapping
            for mapping in (
                mapping_registry.list_mappings(
                    active_only=True
                )
            )
            if (
                mapping.supplier_code
                == SUPPLIER_CODE
            )
        )

        decisions = []

        for mapping in active_mappings:
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

        plan = (
            build_dry_run_sync_plan(
                decisions
            )
        )

    except (
        SupplierFeedError,
        SupplierMappingFeedError,
        ShopifySnapshotError,
    ) as exc:
        print(
            "Dry-run plan status: INVALID"
        )
        print(
            f"Reason: {exc}"
        )
        return 1

    print(
        f"Mode: {plan.mode.value.upper()}"
    )
    print(
        f"Plan fingerprint: "
        f"{plan.fingerprint}"
    )
    print("-" * 64)

    for item_number, item in enumerate(
        plan.items,
        start=1,
    ):
        print(
            f"PLAN ITEM #{item_number}"
        )
        print(
            f"Supplier SKU: "
            f"{item.supplier_sku}"
        )
        print(
            f"Shopify SKU: "
            f"{item.shopify_sku}"
        )
        print(
            f"Decision: "
            f"{item.decision_status.value.upper()}"
        )
        print(
            f"Action: "
            f"{item.action.value.upper()}"
        )
        print(
            "Current inventory: "
            f"{item.current_inventory_quantity}"
        )
        print(
            "Proposed inventory: "
            f"{item.proposed_inventory_quantity}"
        )
        print(
            "Inventory delta: "
            f"{item.inventory_delta}"
        )
        print(
            "Would mutate Shopify: "
            f"{item.would_mutate_shopify}"
        )
        print("-" * 64)

    print(
        f"Plan items: "
        f"{len(plan.items)}"
    )
    print(
        f"Planned mutations: "
        f"{plan.planned_mutations}"
    )
    print(
        f"Review items: "
        f"{plan.review_items}"
    )
    print(
        f"Blocked items: "
        f"{plan.blocked_items}"
    )
    print(
        f"No-action items: "
        f"{plan.no_action_items}"
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

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
