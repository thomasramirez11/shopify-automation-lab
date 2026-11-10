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
from supplier.mapping.json_loader import (  # noqa: E402
    JsonSupplierMappingLoader,
    SupplierMappingFeedError,
)
from supplier.mapping.validator import (  # noqa: E402
    validate_supplier_mapping_catalog,
)


SUPPLIER_CODE = "demo_supplier"


def main() -> int:
    """
    Preview explicit supplier mappings and cross-validate them safely.
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

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2 SUPPLIER MAPPING PREVIEW"
    )
    print("=" * 60)

    try:
        registry = (
            mapping_loader.load_registry()
        )

        report = (
            validate_supplier_mapping_catalog(
                supplier_code=SUPPLIER_CODE,
                supplier_catalog=(
                    supplier_adapter
                ),
                mapping_registry=(
                    registry
                ),
            )
        )

    except (
        SupplierFeedError,
        SupplierMappingFeedError,
    ) as exc:
        print(
            "Mapping validation status: INVALID"
        )
        print(
            f"Reason: {exc}"
        )
        return 1

    for mapping in (
        registry.list_mappings()
    ):
        state = (
            "ACTIVE"
            if mapping.active
            else "INACTIVE"
        )

        print(
            f"[{state}] "
            f"{mapping.supplier_code} / "
            f"{mapping.supplier_sku}"
        )
        print(
            "  -> Shopify SKU: "
            f"{mapping.shopify_sku}"
        )
        print(
            "  -> Shopify Variant: "
            f"{mapping.shopify_variant_id}"
        )

    print("-" * 60)
    print(
        "Mapping validation status: "
        + (
            "VALID"
            if report.passed
            else "INVALID"
        )
    )
    print(
        "Supplier products seen: "
        f"{report.supplier_products_seen}"
    )
    print(
        "Active mappings checked: "
        f"{report.active_mappings_checked}"
    )
    print(
        "Valid mappings: "
        f"{report.valid_mappings}"
    )

    if report.missing_supplier_skus:
        print(
            "Missing mapped supplier SKUs: "
            + ", ".join(
                report.missing_supplier_skus
            )
        )
    else:
        print(
            "Missing mapped supplier SKUs: 0"
        )

    if report.unmapped_supplier_skus:
        print(
            "Unmapped supplier products "
            "(allowed): "
            + ", ".join(
                report.unmapped_supplier_skus
            )
        )
    else:
        print(
            "Unmapped supplier products: 0"
        )

    print(
        "SHOPIFY WRITES PERFORMED: 0"
    )

    return (
        0
        if report.passed
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
