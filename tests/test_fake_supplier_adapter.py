from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from supplier.adapters.fake_supplier import (
    FakeSupplierAdapter,
)
from supplier.models import (
    SupplierDataError,
    SupplierProduct,
)
from supplier.ports import SupplierCatalogPort


def make_product(
    *,
    supplier_sku: str = "SUP-CAP-001",
    title: str = "Automation Test Cap",
    stock_quantity: int = 25,
    unit_cost="4.25",
    currency: str = "usd",
    source_updated_at=None,
) -> SupplierProduct:
    return SupplierProduct(
        supplier_sku=supplier_sku,
        title=title,
        stock_quantity=stock_quantity,
        unit_cost=unit_cost,
        currency=currency,
        source_updated_at=source_updated_at,
    )


def test_supplier_product_normalizes_core_values():
    product = make_product(
        supplier_sku="  SUP-CAP-001  ",
        title="  Automation Test Cap  ",
        currency="usd",
        unit_cost="4.25",
    )

    assert product.supplier_sku == "SUP-CAP-001"
    assert product.title == "Automation Test Cap"
    assert product.currency == "USD"
    assert product.unit_cost == Decimal("4.25")


def test_supplier_product_is_immutable():
    product = make_product()

    with pytest.raises(
        FrozenInstanceError
    ):
        product.stock_quantity = 99


def test_supplier_product_rejects_empty_sku():
    with pytest.raises(
        SupplierDataError,
        match="supplier_sku cannot be empty",
    ):
        make_product(
            supplier_sku="   "
        )


def test_supplier_product_rejects_negative_stock():
    with pytest.raises(
        SupplierDataError,
        match="stock_quantity cannot be negative",
    ):
        make_product(
            stock_quantity=-1
        )


def test_supplier_product_rejects_non_integer_stock():
    with pytest.raises(
        SupplierDataError,
        match="stock_quantity must be an integer",
    ):
        make_product(
            stock_quantity=2.5
        )


def test_supplier_product_rejects_invalid_cost():
    with pytest.raises(
        SupplierDataError,
        match="unit_cost must be a valid decimal number",
    ):
        make_product(
            unit_cost="not-money"
        )


def test_supplier_product_rejects_negative_cost():
    with pytest.raises(
        SupplierDataError,
        match="unit_cost cannot be negative",
    ):
        make_product(
            unit_cost="-0.01"
        )


def test_supplier_product_rejects_invalid_currency():
    with pytest.raises(
        SupplierDataError,
        match="currency must be a 3-letter code",
    ):
        make_product(
            currency="US"
        )


def test_supplier_product_requires_timezone_aware_timestamp():
    with pytest.raises(
        SupplierDataError,
        match="source_updated_at must be timezone-aware",
    ):
        make_product(
            source_updated_at=datetime(
                2026,
                11,
                10,
                12,
                0,
                0,
            )
        )


def test_supplier_product_accepts_timezone_aware_timestamp():
    timestamp = datetime(
        2026,
        11,
        10,
        12,
        0,
        0,
        tzinfo=timezone.utc,
    )

    product = make_product(
        source_updated_at=timestamp
    )

    assert (
        product.source_updated_at
        == timestamp
    )


def test_fake_adapter_lists_products_without_shopify_dependency():
    first = make_product()
    second = make_product(
        supplier_sku="SUP-SHIRT-001",
        title="Automation Shirt",
        stock_quantity=12,
        unit_cost="3.00",
    )

    adapter = FakeSupplierAdapter(
        [first, second]
    )

    assert adapter.list_products() == (
        first,
        second,
    )


def test_fake_adapter_fulfills_supplier_catalog_port_contract():
    adapter: SupplierCatalogPort = (
        FakeSupplierAdapter(
            [make_product()]
        )
    )

    assert len(
        adapter.list_products()
    ) == 1


def test_fake_adapter_finds_product_by_sku():
    product = make_product()

    adapter = FakeSupplierAdapter(
        [product]
    )

    assert (
        adapter.get_product_by_sku(
            "  SUP-CAP-001  "
        )
        == product
    )


def test_fake_adapter_returns_none_for_unknown_sku():
    adapter = FakeSupplierAdapter(
        [make_product()]
    )

    assert (
        adapter.get_product_by_sku(
            "SUP-UNKNOWN"
        )
        is None
    )


def test_fake_adapter_rejects_duplicate_supplier_skus():
    first = make_product()
    duplicate = make_product(
        title="Duplicate row"
    )

    with pytest.raises(
        SupplierDataError,
        match="Duplicate supplier SKU",
    ):
        FakeSupplierAdapter(
            [first, duplicate]
        )
