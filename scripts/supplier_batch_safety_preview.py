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
    SupplierFeedError,
)
from supplier.batch.builder import (  # noqa: E402
    build_batch_safety_manifest,
)
from supplier.batch.models import (  # noqa: E402
    BatchSafetyPolicy,
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

ITEM_POLICY_MAX_DELTA = 50

BATCH_POLICY = BatchSafetyPolicy(
    max_mutations_per_batch=5,
    max_total_absolute_inventory_delta=100,
    max_single_item_absolute_delta=50,
)


def main() -> int:
    """
    Build a read-only batch safety manifest from the current trusted V1 state.
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

    item_policy = InventorySyncPolicy(
        max_inventory_delta=(
            ITEM_POLICY_MAX_DELTA
        )
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.6 BATCH SAFETY MANIFEST"
    )
    print("=" * 72)
    print(
        "MODE: READ ONLY"
    )
    print(
        "EXECUTION CAPABILITY: DISABLED"
    )
    print("-" * 72)

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
                    policy=item_policy,
                )
            )

        plan = build_dry_run_sync_plan(
            decisions
        )

        manifest = (
            build_batch_safety_manifest(
                plan=plan,
                policy=BATCH_POLICY,
            )
        )

    except (
        SupplierFeedError,
        SupplierMappingFeedError,
        ShopifySnapshotError,
    ) as exc:
        print(
            "Batch manifest status: INVALID"
        )
        print(
            f"Reason: {exc}"
        )
        return 1

    print(
        "BLAST-RADIUS BUDGET"
    )
    print("-" * 72)
    print(
        "Max mutations per batch: "
        f"{manifest.policy.max_mutations_per_batch}"
    )
    print(
        "Max total absolute inventory delta: "
        f"{manifest.policy.max_total_absolute_inventory_delta}"
    )
    print(
        "Max single-item absolute delta: "
        f"{manifest.policy.max_single_item_absolute_delta}"
    )
    print("-" * 72)

    print(
        f"Source plan fingerprint:"
    )
    print(
        manifest.source_plan_fingerprint
    )
    print(
        f"Batch manifest fingerprint:"
    )
    print(
        manifest.manifest_fingerprint
    )
    print("-" * 72)

    if manifest.mutations:
        print(
            "PLANNED BATCH MUTATIONS"
        )
        print("-" * 72)

        for index, item in enumerate(
            manifest.mutations,
            start=1,
        ):
            print(
                f"Mutation #{index}"
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
                "Absolute delta: "
                f"{item.absolute_inventory_delta}"
            )
            print("-" * 72)

    else:
        print(
            "PLANNED BATCH MUTATIONS"
        )
        print("-" * 72)
        print(
            "None — current mapped supplier inventory already matches "
            "the trusted V1 state or is not eligible."
        )
        print("-" * 72)

    print(
        "BATCH SAFETY SUMMARY"
    )
    print("-" * 72)
    print(
        f"Status: "
        f"{manifest.status.value.upper()}"
    )
    print(
        "Reasons: "
        + ", ".join(
            reason.value
            for reason in manifest.reasons
        )
    )
    print(
        f"Planned mutations: "
        f"{manifest.planned_mutations}"
    )
    print(
        f"Review items: "
        f"{manifest.review_items}"
    )
    print(
        f"Blocked items: "
        f"{manifest.blocked_items}"
    )
    print(
        f"No-action items: "
        f"{manifest.no_action_items}"
    )
    print(
        "Total absolute inventory delta: "
        f"{manifest.total_absolute_inventory_delta}"
    )
    print(
        "Largest single-item absolute delta: "
        f"{manifest.largest_single_item_absolute_delta}"
    )
    print(
        f"Batch executable in this checkpoint: False"
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
