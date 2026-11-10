import json
from datetime import timezone
from decimal import Decimal

import pytest

from supplier.adapters.json_file_supplier import (
    JsonFileSupplierAdapter,
    SupplierFeedError,
)


def write_feed(
    tmp_path,
    payload,
):
    path = (
        tmp_path
        / "supplier_feed.json"
    )

    path.write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )

    return path


def valid_record(
    **overrides,
):
    record = {
        "sku": "SUP-CAP-001",
        "name": "Automation Test Cap",
        "available": 25,
        "cost": "4.25",
        "currency": "usd",
        "updated_at":
            "2026-11-10T21:00:00Z",
    }

    record.update(
        overrides
    )

    return record


def test_json_adapter_normalizes_valid_supplier_feed(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        [
            valid_record()
        ],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    products = (
        adapter.list_products()
    )

    assert len(products) == 1

    product = products[0]

    assert (
        product.supplier_sku
        == "SUP-CAP-001"
    )

    assert (
        product.stock_quantity
        == 25
    )

    assert (
        product.unit_cost
        == Decimal("4.25")
    )

    assert (
        product.currency
        == "USD"
    )

    assert (
        product.source_updated_at
        .utcoffset()
        == timezone.utc.utcoffset(
            None
        )
    )


def test_json_adapter_supports_multiple_products(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        [
            valid_record(),
            valid_record(
                sku="SUP-SHIRT-001",
                name="Automation Shirt",
                available=12,
                cost="3.00",
            ),
        ],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    products = (
        adapter.list_products()
    )

    assert [
        product.supplier_sku
        for product in products
    ] == [
        "SUP-CAP-001",
        "SUP-SHIRT-001",
    ]


def test_json_adapter_gets_product_by_sku(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        [
            valid_record()
        ],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    product = (
        adapter.get_product_by_sku(
            "  SUP-CAP-001  "
        )
    )

    assert product is not None

    assert (
        product.title
        == "Automation Test Cap"
    )


def test_json_adapter_returns_none_for_unknown_sku(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        [
            valid_record()
        ],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    assert (
        adapter.get_product_by_sku(
            "SUP-UNKNOWN"
        )
        is None
    )


def test_missing_feed_file_is_rejected(
    tmp_path,
):
    adapter = (
        JsonFileSupplierAdapter(
            tmp_path
            / "missing.json"
        )
    )

    with pytest.raises(
        SupplierFeedError,
        match="does not exist",
    ):
        adapter.list_products()


def test_malformed_json_is_rejected(
    tmp_path,
):
    path = (
        tmp_path
        / "supplier_feed.json"
    )

    path.write_text(
        "{broken-json",
        encoding="utf-8",
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    with pytest.raises(
        SupplierFeedError,
        match="invalid JSON",
    ):
        adapter.list_products()


def test_non_array_root_is_rejected(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        valid_record(),
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    with pytest.raises(
        SupplierFeedError,
        match="root must be a JSON array",
    ):
        adapter.list_products()


def test_non_object_row_is_rejected(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        [
            "not-an-object"
        ],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    with pytest.raises(
        SupplierFeedError,
        match="must be a JSON object",
    ):
        adapter.list_products()


def test_missing_required_field_is_rejected(
    tmp_path,
):
    record = valid_record()

    record.pop(
        "cost"
    )

    path = write_feed(
        tmp_path,
        [record],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    with pytest.raises(
        SupplierFeedError,
        match="missing required field",
    ):
        adapter.list_products()


def test_negative_stock_is_rejected(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        [
            valid_record(
                available=-1
            )
        ],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    with pytest.raises(
        SupplierFeedError,
        match="stock_quantity cannot be negative",
    ):
        adapter.list_products()


def test_invalid_cost_is_rejected(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        [
            valid_record(
                cost="bad-money"
            )
        ],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    with pytest.raises(
        SupplierFeedError,
        match="unit_cost must be a valid decimal",
    ):
        adapter.list_products()


def test_invalid_currency_is_rejected(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        [
            valid_record(
                currency="US"
            )
        ],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    with pytest.raises(
        SupplierFeedError,
        match="currency must be a 3-letter code",
    ):
        adapter.list_products()


def test_invalid_timestamp_is_rejected(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        [
            valid_record(
                updated_at="not-a-date"
            )
        ],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    with pytest.raises(
        SupplierFeedError,
        match="valid ISO-8601",
    ):
        adapter.list_products()


def test_timestamp_without_timezone_is_rejected(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        [
            valid_record(
                updated_at=(
                    "2026-11-10T21:00:00"
                )
            )
        ],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    with pytest.raises(
        SupplierFeedError,
        match="timezone information",
    ):
        adapter.list_products()


def test_duplicate_supplier_sku_is_rejected(
    tmp_path,
):
    path = write_feed(
        tmp_path,
        [
            valid_record(),
            valid_record(
                name="Duplicate row"
            ),
        ],
    )

    adapter = (
        JsonFileSupplierAdapter(
            path
        )
    )

    with pytest.raises(
        SupplierFeedError,
        match="Duplicate supplier SKU",
    ):
        adapter.list_products()
