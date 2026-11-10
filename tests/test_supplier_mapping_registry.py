from dataclasses import FrozenInstanceError

import pytest

from supplier.mapping.memory_registry import (
    InMemorySupplierMappingRegistry,
)
from supplier.mapping.models import (
    SupplierMappingError,
    SupplierVariantMapping,
)
from supplier.mapping.ports import (
    SupplierMappingPort,
)


def make_mapping(
    *,
    supplier_code: str = "demo_supplier",
    supplier_sku: str = "SUP-CAP-001",
    shopify_variant_id: str = (
        "gid://shopify/ProductVariant/56166258147700"
    ),
    shopify_sku: str = "AUTO-Cap-001",
    active: bool = True,
) -> SupplierVariantMapping:
    return SupplierVariantMapping(
        supplier_code=supplier_code,
        supplier_sku=supplier_sku,
        shopify_variant_id=shopify_variant_id,
        shopify_sku=shopify_sku,
        active=active,
    )


def test_mapping_normalizes_supplier_code_and_whitespace():
    mapping = make_mapping(
        supplier_code="  Demo_Supplier  ",
        supplier_sku="  SUP-CAP-001  ",
        shopify_sku="  AUTO-Cap-001  ",
    )

    assert (
        mapping.supplier_code
        == "demo_supplier"
    )
    assert (
        mapping.supplier_sku
        == "SUP-CAP-001"
    )
    assert (
        mapping.shopify_sku
        == "AUTO-Cap-001"
    )


def test_mapping_exposes_stable_supplier_key():
    mapping = make_mapping()

    assert mapping.supplier_key == (
        "demo_supplier",
        "SUP-CAP-001",
    )


def test_mapping_is_immutable():
    mapping = make_mapping()

    with pytest.raises(
        FrozenInstanceError
    ):
        mapping.shopify_sku = "CHANGED"


def test_mapping_rejects_empty_supplier_code():
    with pytest.raises(
        SupplierMappingError,
        match="supplier_code cannot be empty",
    ):
        make_mapping(
            supplier_code="   "
        )


def test_mapping_rejects_invalid_supplier_code():
    with pytest.raises(
        SupplierMappingError,
        match="supplier_code must contain",
    ):
        make_mapping(
            supplier_code="Supplier One!"
        )


def test_mapping_rejects_empty_supplier_sku():
    with pytest.raises(
        SupplierMappingError,
        match="supplier_sku cannot be empty",
    ):
        make_mapping(
            supplier_sku="   "
        )


def test_mapping_rejects_non_variant_shopify_gid():
    with pytest.raises(
        SupplierMappingError,
        match="Shopify ProductVariant GID",
    ):
        make_mapping(
            shopify_variant_id=(
                "gid://shopify/Product/123"
            )
        )


def test_mapping_rejects_malformed_variant_gid():
    with pytest.raises(
        SupplierMappingError,
        match="Shopify ProductVariant GID",
    ):
        make_mapping(
            shopify_variant_id="12345"
        )


def test_mapping_rejects_empty_shopify_sku():
    with pytest.raises(
        SupplierMappingError,
        match="shopify_sku cannot be empty",
    ):
        make_mapping(
            shopify_sku="   "
        )


def test_mapping_rejects_non_boolean_active():
    with pytest.raises(
        SupplierMappingError,
        match="active must be a boolean",
    ):
        make_mapping(
            active="yes"
        )


def test_registry_lists_mappings_in_insertion_order():
    first = make_mapping()

    second = make_mapping(
        supplier_sku="SUP-SHIRT-L",
        shopify_variant_id=(
            "gid://shopify/ProductVariant/56166256607604"
        ),
        shopify_sku="AUTO-shirt-L",
    )

    registry = (
        InMemorySupplierMappingRegistry(
            [first, second]
        )
    )

    assert registry.list_mappings() == (
        first,
        second,
    )


def test_registry_can_filter_inactive_mappings():
    active = make_mapping()

    inactive = make_mapping(
        supplier_sku="SUP-SHIRT-L",
        shopify_variant_id=(
            "gid://shopify/ProductVariant/56166256607604"
        ),
        shopify_sku="AUTO-shirt-L",
        active=False,
    )

    registry = (
        InMemorySupplierMappingRegistry(
            [active, inactive]
        )
    )

    assert (
        registry.list_mappings(
            active_only=True
        )
        == (active,)
    )


def test_registry_resolves_by_supplier_identity():
    mapping = make_mapping()

    registry = (
        InMemorySupplierMappingRegistry(
            [mapping]
        )
    )

    assert (
        registry.get_by_supplier(
            "  DEMO_SUPPLIER  ",
            "  SUP-CAP-001  ",
        )
        == mapping
    )


def test_registry_resolves_by_shopify_variant_id():
    mapping = make_mapping()

    registry = (
        InMemorySupplierMappingRegistry(
            [mapping]
        )
    )

    assert (
        registry.get_by_shopify_variant_id(
            "  gid://shopify/ProductVariant/56166258147700  "
        )
        == mapping
    )


def test_registry_returns_none_for_unknown_supplier_mapping():
    registry = (
        InMemorySupplierMappingRegistry(
            [make_mapping()]
        )
    )

    assert (
        registry.get_by_supplier(
            "demo_supplier",
            "SUP-UNKNOWN",
        )
        is None
    )


def test_registry_rejects_duplicate_supplier_identity():
    first = make_mapping()

    duplicate = make_mapping(
        shopify_variant_id=(
            "gid://shopify/ProductVariant/999999"
        ),
        shopify_sku="OTHER-SKU",
    )

    with pytest.raises(
        SupplierMappingError,
        match="Duplicate supplier mapping",
    ):
        InMemorySupplierMappingRegistry(
            [first, duplicate]
        )


def test_registry_rejects_two_suppliers_controlling_same_variant():
    first = make_mapping()

    conflicting = make_mapping(
        supplier_code="backup_supplier",
        supplier_sku="BACKUP-CAP-001",
    )

    with pytest.raises(
        SupplierMappingError,
        match="already mapped",
    ):
        InMemorySupplierMappingRegistry(
            [first, conflicting]
        )


def test_registry_fulfills_mapping_port_contract():
    registry: SupplierMappingPort = (
        InMemorySupplierMappingRegistry(
            [make_mapping()]
        )
    )

    assert len(
        registry.list_mappings()
    ) == 1
