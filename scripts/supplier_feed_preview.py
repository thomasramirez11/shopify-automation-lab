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


def main() -> int:
    """
    Preview a simulated supplier feed without touching Shopify.
    """

    feed_path = (
        PROJECT_ROOT
        / "supplier"
        / "samples"
        / "sample_supplier_feed.json"
    )

    adapter = (
        JsonFileSupplierAdapter(
            feed_path
        )
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2 SUPPLIER FEED PREVIEW"
    )
    print("=" * 52)

    try:
        products = (
            adapter.list_products()
        )

    except SupplierFeedError as exc:
        print(
            "Supplier feed status: INVALID"
        )
        print(
            f"Reason: {exc}"
        )
        return 1

    print(
        "Supplier feed status: VALID"
    )
    print(
        f"Products normalized: "
        f"{len(products)}"
    )
    print()

    for product in products:
        print(
            f"SKU: {product.supplier_sku}"
        )
        print(
            f"Title: {product.title}"
        )
        print(
            f"Supplier stock: "
            f"{product.stock_quantity}"
        )
        print(
            f"Supplier cost: "
            f"{product.unit_cost} "
            f"{product.currency}"
        )
        print(
            "Supplier updated at: "
            f"{product.source_updated_at.isoformat()}"
        )
        print("-" * 52)

    print(
        "SHOPIFY WRITES PERFORMED: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
