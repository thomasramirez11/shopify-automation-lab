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
from supplier.mapping.json_loader import (  # noqa: E402
    JsonSupplierMappingLoader,
    SupplierMappingFeedError,
)


SUPPLIER_CODE = "demo_supplier"


def main() -> int:
    """
    Compare simulated supplier data to the last trusted V1 SQLite state.

    This command is read-only.
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

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2 SUPPLIER COMPARISON PREVIEW"
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

        comparisons = []

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

            comparisons.append(
                (
                    comparison,
                    snapshot,
                )
            )

    except (
        SupplierFeedError,
        SupplierMappingFeedError,
        ShopifySnapshotError,
    ) as exc:
        print(
            "Comparison preview status: INVALID"
        )
        print(
            f"Reason: {exc}"
        )
        return 1

    for comparison, snapshot in comparisons:
        print(
            f"Supplier SKU: "
            f"{comparison.supplier_sku}"
        )
        print(
            f"Shopify SKU: "
            f"{comparison.shopify_sku}"
        )
        print(
            f"Status: "
            f"{comparison.status.value.upper()}"
        )

        print(
            "Supplier stock: "
            f"{comparison.supplier_stock}"
        )
        print(
            "Shopify stock: "
            f"{comparison.shopify_stock}"
        )
        print(
            "Stock difference: "
            f"{comparison.stock_difference}"
        )

        print(
            "Supplier cost: "
            f"{comparison.supplier_cost}"
        )
        print(
            "Stored cost: "
            f"{comparison.stored_cost}"
        )
        print(
            "Cost difference: "
            f"{comparison.cost_difference}"
        )

        if (
            snapshot is not None
            and snapshot.stored_cost
            is not None
        ):
            print(
                "Stored cost metadata: "
                f"{snapshot.cost_currency or 'N/A'} / "
                f"{snapshot.cost_source or 'N/A'}"
            )

        print("-" * 64)

    actionable_count = sum(
        1
        for comparison, _
        in comparisons
        if comparison.is_actionable
    )

    print(
        f"Comparisons processed: "
        f"{len(comparisons)}"
    )
    print(
        f"Actionable differences: "
        f"{actionable_count}"
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
