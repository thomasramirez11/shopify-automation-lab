import json

import pytest

from supplier.adapters.fake_supplier import (
    FakeSupplierAdapter,
)
from supplier.mapping.json_loader import (
    JsonSupplierMappingLoader,
    SupplierMappingFeedError,
)
from supplier.mapping.memory_registry import (
    InMemorySupplierMappingRegistry,
)
from supplier.mapping.models import (
    SupplierVariantMapping,
)
from supplier.mapping.validator import (
    validate_supplier_mapping_catalog,
)
from supplier.models import (
    SupplierProduct,
)


CAP_VARIANT_ID = (
    "gid://shopify/ProductVariant/56166258147700"
)

SHIRT_VARIANT_ID = (
    "gid://shopify/ProductVariant/56166256607604"
)


def valid_mapping_row(
    **overrides,
):
    row = {
        "supplier_code": "demo_supplier",
        "supplier_sku": "SUP-CAP-001",
        "shopify_variant_id":
            CAP_VARIANT_ID,
        "shopify_sku":
            "AUTO-Cap-001",
        "active": True,
    }

    row.update(
        overrides
    )

    return row


def write_mapping_feed(
    tmp_path,
    payload,
):
    path = (
        tmp_path
        / "supplier_mappings.json"
    )

    path.write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )

    return path


def supplier_product(
    supplier_sku,
):
    return SupplierProduct(
        supplier_sku=(
            supplier_sku
        ),
        title=(
            f"Product {supplier_sku}"
        ),
        stock_quantity=10,
        unit_cost="4.25",
        currency="USD",
    )


def test_loader_loads_valid_mapping(
    tmp_path,
):
    path = write_mapping_feed(
        tmp_path,
        [
            valid_mapping_row()
        ],
    )

    loader = (
        JsonSupplierMappingLoader(
            path
        )
    )

    mappings = (
        loader.load_mappings()
    )

    assert len(mappings) == 1
    assert (
        mappings[0].supplier_code
        == "demo_supplier"
    )
    assert (
        mappings[0].supplier_sku
        == "SUP-CAP-001"
    )


def test_loader_defaults_active_to_true(
    tmp_path,
):
    row = valid_mapping_row()
    row.pop(
        "active"
    )

    path = write_mapping_feed(
        tmp_path,
        [row],
    )

    mapping = (
        JsonSupplierMappingLoader(
            path
        )
        .load_mappings()[0]
    )

    assert mapping.active is True


def test_loader_supports_multiple_mappings(
    tmp_path,
):
    path = write_mapping_feed(
        tmp_path,
        [
            valid_mapping_row(),
            valid_mapping_row(
                supplier_sku=(
                    "SUP-SHIRT-L"
                ),
                shopify_variant_id=(
                    SHIRT_VARIANT_ID
                ),
                shopify_sku=(
                    "AUTO-shirt-L"
                ),
            ),
        ],
    )

    mappings = (
        JsonSupplierMappingLoader(
            path
        )
        .load_mappings()
    )

    assert len(mappings) == 2


def test_loader_rejects_missing_file(
    tmp_path,
):
    loader = (
        JsonSupplierMappingLoader(
            tmp_path
            / "missing.json"
        )
    )

    with pytest.raises(
        SupplierMappingFeedError,
        match="does not exist",
    ):
        loader.load_mappings()


def test_loader_rejects_malformed_json(
    tmp_path,
):
    path = (
        tmp_path
        / "bad.json"
    )

    path.write_text(
        "{bad-json",
        encoding="utf-8",
    )

    with pytest.raises(
        SupplierMappingFeedError,
        match="invalid JSON",
    ):
        JsonSupplierMappingLoader(
            path
        ).load_mappings()


def test_loader_rejects_non_array_root(
    tmp_path,
):
    path = write_mapping_feed(
        tmp_path,
        valid_mapping_row(),
    )

    with pytest.raises(
        SupplierMappingFeedError,
        match="root must be a JSON array",
    ):
        JsonSupplierMappingLoader(
            path
        ).load_mappings()


def test_loader_rejects_non_object_row(
    tmp_path,
):
    path = write_mapping_feed(
        tmp_path,
        ["not-an-object"],
    )

    with pytest.raises(
        SupplierMappingFeedError,
        match="must be a JSON object",
    ):
        JsonSupplierMappingLoader(
            path
        ).load_mappings()


def test_loader_rejects_missing_required_field(
    tmp_path,
):
    row = valid_mapping_row()
    row.pop(
        "shopify_sku"
    )

    path = write_mapping_feed(
        tmp_path,
        [row],
    )

    with pytest.raises(
        SupplierMappingFeedError,
        match="missing required field",
    ):
        JsonSupplierMappingLoader(
            path
        ).load_mappings()


def test_loader_reports_invalid_mapping_with_row_number(
    tmp_path,
):
    path = write_mapping_feed(
        tmp_path,
        [
            valid_mapping_row(
                shopify_variant_id=(
                    "not-a-gid"
                )
            )
        ],
    )

    with pytest.raises(
        SupplierMappingFeedError,
        match="row 1 is invalid",
    ):
        JsonSupplierMappingLoader(
            path
        ).load_mappings()


def test_loader_registry_rejects_duplicate_supplier_mapping(
    tmp_path,
):
    path = write_mapping_feed(
        tmp_path,
        [
            valid_mapping_row(),
            valid_mapping_row(
                shopify_variant_id=(
                    SHIRT_VARIANT_ID
                ),
                shopify_sku=(
                    "AUTO-shirt-L"
                ),
            ),
        ],
    )

    with pytest.raises(
        SupplierMappingFeedError,
        match="conflicting mappings",
    ):
        JsonSupplierMappingLoader(
            path
        ).load_registry()


def test_loader_registry_rejects_same_shopify_variant_for_two_suppliers(
    tmp_path,
):
    path = write_mapping_feed(
        tmp_path,
        [
            valid_mapping_row(),
            valid_mapping_row(
                supplier_code=(
                    "backup_supplier"
                ),
                supplier_sku=(
                    "BACKUP-CAP-001"
                ),
            ),
        ],
    )

    with pytest.raises(
        SupplierMappingFeedError,
        match="conflicting mappings",
    ):
        JsonSupplierMappingLoader(
            path
        ).load_registry()


def test_validation_passes_when_all_active_mappings_exist():
    mappings = (
        InMemorySupplierMappingRegistry(
            [
                SupplierVariantMapping(
                    supplier_code=(
                        "demo_supplier"
                    ),
                    supplier_sku=(
                        "SUP-CAP-001"
                    ),
                    shopify_variant_id=(
                        CAP_VARIANT_ID
                    ),
                    shopify_sku=(
                        "AUTO-Cap-001"
                    ),
                )
            ]
        )
    )

    catalog = FakeSupplierAdapter(
        [
            supplier_product(
                "SUP-CAP-001"
            )
        ]
    )

    report = (
        validate_supplier_mapping_catalog(
            supplier_code=(
                "demo_supplier"
            ),
            supplier_catalog=catalog,
            mapping_registry=mappings,
        )
    )

    assert report.passed is True
    assert (
        report.valid_mappings
        == 1
    )
    assert (
        report.missing_supplier_skus
        == ()
    )


def test_validation_blocks_mapping_to_missing_supplier_sku():
    mappings = (
        InMemorySupplierMappingRegistry(
            [
                SupplierVariantMapping(
                    supplier_code=(
                        "demo_supplier"
                    ),
                    supplier_sku=(
                        "SUP-MISSING"
                    ),
                    shopify_variant_id=(
                        CAP_VARIANT_ID
                    ),
                    shopify_sku=(
                        "AUTO-Cap-001"
                    ),
                )
            ]
        )
    )

    catalog = FakeSupplierAdapter(
        [
            supplier_product(
                "SUP-CAP-001"
            )
        ]
    )

    report = (
        validate_supplier_mapping_catalog(
            supplier_code=(
                "demo_supplier"
            ),
            supplier_catalog=catalog,
            mapping_registry=mappings,
        )
    )

    assert report.passed is False
    assert (
        report.missing_supplier_skus
        == ("SUP-MISSING",)
    )


def test_unmapped_supplier_product_is_allowed_and_reported():
    mappings = (
        InMemorySupplierMappingRegistry(
            [
                SupplierVariantMapping(
                    supplier_code=(
                        "demo_supplier"
                    ),
                    supplier_sku=(
                        "SUP-CAP-001"
                    ),
                    shopify_variant_id=(
                        CAP_VARIANT_ID
                    ),
                    shopify_sku=(
                        "AUTO-Cap-001"
                    ),
                )
            ]
        )
    )

    catalog = FakeSupplierAdapter(
        [
            supplier_product(
                "SUP-CAP-001"
            ),
            supplier_product(
                "SUP-EXTRA-001"
            ),
        ]
    )

    report = (
        validate_supplier_mapping_catalog(
            supplier_code=(
                "demo_supplier"
            ),
            supplier_catalog=catalog,
            mapping_registry=mappings,
        )
    )

    assert report.passed is True
    assert (
        report.unmapped_supplier_skus
        == ("SUP-EXTRA-001",)
    )


def test_inactive_missing_mapping_is_ignored():
    mappings = (
        InMemorySupplierMappingRegistry(
            [
                SupplierVariantMapping(
                    supplier_code=(
                        "demo_supplier"
                    ),
                    supplier_sku=(
                        "SUP-MISSING"
                    ),
                    shopify_variant_id=(
                        CAP_VARIANT_ID
                    ),
                    shopify_sku=(
                        "AUTO-Cap-001"
                    ),
                    active=False,
                )
            ]
        )
    )

    catalog = FakeSupplierAdapter(
        [
            supplier_product(
                "SUP-CAP-001"
            )
        ]
    )

    report = (
        validate_supplier_mapping_catalog(
            supplier_code=(
                "demo_supplier"
            ),
            supplier_catalog=catalog,
            mapping_registry=mappings,
        )
    )

    assert report.passed is True
    assert (
        report.active_mappings_checked
        == 0
    )


def test_validation_scopes_mappings_by_supplier_code():
    mappings = (
        InMemorySupplierMappingRegistry(
            [
                SupplierVariantMapping(
                    supplier_code=(
                        "demo_supplier"
                    ),
                    supplier_sku=(
                        "SUP-CAP-001"
                    ),
                    shopify_variant_id=(
                        CAP_VARIANT_ID
                    ),
                    shopify_sku=(
                        "AUTO-Cap-001"
                    ),
                ),
                SupplierVariantMapping(
                    supplier_code=(
                        "other_supplier"
                    ),
                    supplier_sku=(
                        "OTHER-SHIRT"
                    ),
                    shopify_variant_id=(
                        SHIRT_VARIANT_ID
                    ),
                    shopify_sku=(
                        "AUTO-shirt-L"
                    ),
                ),
            ]
        )
    )

    catalog = FakeSupplierAdapter(
        [
            supplier_product(
                "SUP-CAP-001"
            )
        ]
    )

    report = (
        validate_supplier_mapping_catalog(
            supplier_code=(
                "DEMO_SUPPLIER"
            ),
            supplier_catalog=catalog,
            mapping_registry=mappings,
        )
    )

    assert report.passed is True
    assert (
        report.active_mappings_checked
        == 1
    )


def test_validation_counts_supplier_products():
    registry = (
        InMemorySupplierMappingRegistry(
            []
        )
    )

    catalog = FakeSupplierAdapter(
        [
            supplier_product(
                "SUP-CAP-001"
            ),
            supplier_product(
                "SUP-SHIRT-L"
            ),
        ]
    )

    report = (
        validate_supplier_mapping_catalog(
            supplier_code=(
                "demo_supplier"
            ),
            supplier_catalog=catalog,
            mapping_registry=registry,
        )
    )

    assert (
        report.supplier_products_seen
        == 2
    )


def test_validation_with_no_mappings_is_safe_but_reports_unmapped_products():
    registry = (
        InMemorySupplierMappingRegistry(
            []
        )
    )

    catalog = FakeSupplierAdapter(
        [
            supplier_product(
                "SUP-CAP-001"
            )
        ]
    )

    report = (
        validate_supplier_mapping_catalog(
            supplier_code=(
                "demo_supplier"
            ),
            supplier_catalog=catalog,
            mapping_registry=registry,
        )
    )

    assert report.passed is True
    assert (
        report.unmapped_supplier_skus
        == ("SUP-CAP-001",)
    )
