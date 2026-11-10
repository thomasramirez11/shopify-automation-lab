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


SUPPLIER_CODE = "demo_supplier"

# Conservative V2 development threshold.
# Larger changes are not rejected forever; they are routed to REVIEW.
MAX_INVENTORY_DELTA = 50


def main() -> int:
    """
    Build inventory synchronization recommendations without performing writes.
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
        "V2 SAFE SYNC DECISION PREVIEW"
    )
    print("=" * 64)
    print(
        "Inventory auto-eligibility limit: "
        f"{policy.max_inventory_delta}"
    )
    print("-" * 64)

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

            decision = (
                evaluate_supplier_sync_decision(
                    comparison=comparison,
                    policy=policy,
                )
            )

            decisions.append(
                decision
            )

    except (
        SupplierFeedError,
        SupplierMappingFeedError,
        ShopifySnapshotError,
    ) as exc:
        print(
            "Decision preview status: INVALID"
        )
        print(
            f"Reason: {exc}"
        )
        return 1

    for decision in decisions:
        print(
            f"Supplier SKU: "
            f"{decision.supplier_sku}"
        )
        print(
            f"Shopify SKU: "
            f"{decision.shopify_sku}"
        )
        print(
            "Current Shopify inventory: "
            f"{decision.current_inventory_quantity}"
        )
        print(
            "Supplier inventory: "
            f"{decision.supplier_inventory_quantity}"
        )
        print(
            "Inventory delta: "
            f"{decision.inventory_delta}"
        )
        print(
            f"Decision: "
            f"{decision.status.value.upper()}"
        )
        print(
            f"Reason: "
            f"{decision.reason.value}"
        )
        print(
            "Proposed inventory quantity: "
            f"{decision.proposed_inventory_quantity}"
        )
        print("-" * 64)

    eligible = sum(
        1
        for decision in decisions
        if decision.is_eligible
    )

    review = sum(
        1
        for decision in decisions
        if decision.requires_human_review
    )

    blocked = sum(
        1
        for decision in decisions
        if decision.is_blocked
    )

    no_action = (
        len(decisions)
        - eligible
        - review
        - blocked
    )

    print(
        f"Decisions processed: "
        f"{len(decisions)}"
    )
    print(
        f"Eligible: {eligible}"
    )
    print(
        f"Review: {review}"
    )
    print(
        f"Blocked: {blocked}"
    )
    print(
        f"No action: {no_action}"
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
