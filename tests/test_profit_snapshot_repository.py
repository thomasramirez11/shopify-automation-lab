import sqlite3
from contextlib import contextmanager

import pytest

import repositories.profit_snapshot_repository as repository_module
from repositories.profit_snapshot_repository import (
    ProfitSnapshotRepository,
)


CREATE_SNAPSHOT_TABLE_SQL = """
CREATE TABLE order_line_item_profit_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    shopify_line_item_id TEXT NOT NULL UNIQUE,

    shopify_order_id TEXT NOT NULL,

    shopify_variant_id TEXT,

    sku TEXT,

    quantity INTEGER NOT NULL
        CHECK (quantity >= 0),

    currency_code TEXT NOT NULL,

    unit_sale_price TEXT NOT NULL,

    unit_cost TEXT NOT NULL,

    line_revenue TEXT NOT NULL,

    line_cost TEXT NOT NULL,

    estimated_gross_profit TEXT NOT NULL,

    gross_margin_percent TEXT,

    cost_source TEXT NOT NULL,

    calculated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest.fixture
def snapshot_repository(
    tmp_path,
    monkeypatch,
):
    """
    Return a ProfitSnapshotRepository connected to an
    isolated temporary SQLite database.

    The production repository normally uses the real
    application database through get_db_connection().

    For tests, monkeypatch replaces that connection
    function only inside this repository module.
    """

    database_path = (
        tmp_path
        / "profit_snapshot_test.db"
    )

    connection = sqlite3.connect(
        database_path
    )

    try:
        connection.executescript(
            CREATE_SNAPSHOT_TABLE_SQL
        )

        connection.commit()
    finally:
        connection.close()

    @contextmanager
    def temporary_db_connection():
        connection = sqlite3.connect(
            database_path
        )

        connection.row_factory = sqlite3.Row

        try:
            yield connection

            connection.commit()

        except sqlite3.Error:
            connection.rollback()
            raise

        finally:
            connection.close()

    monkeypatch.setattr(
        repository_module,
        "get_db_connection",
        temporary_db_connection,
    )

    return ProfitSnapshotRepository()


@pytest.fixture
def standard_calculation():
    """
    Reusable successful ProfitService-style result.
    """

    return {
        "currency_code": "USD",
        "quantity": 1,
        "unit_sale_price": "10.00",
        "unit_cost": "4.25",
        "line_revenue": "10.00",
        "line_cost": "4.25",
        "estimated_gross_profit": "5.75",
        "gross_margin_percent": "57.50",
    }


def test_save_snapshot_creates_one_record(
    snapshot_repository,
    standard_calculation,
):
    created = snapshot_repository.save_snapshot(
        shopify_line_item_id="line-001",
        shopify_order_id="order-001",
        shopify_variant_id="variant-001",
        sku="AUTO-CAP-001",
        calculation=standard_calculation,
        cost_source="manual",
    )

    assert created is True
    assert snapshot_repository.count_snapshots() == 1


def test_saved_snapshot_can_be_retrieved(
    snapshot_repository,
    standard_calculation,
):
    snapshot_repository.save_snapshot(
        shopify_line_item_id="line-001",
        shopify_order_id="order-001",
        shopify_variant_id="variant-001",
        sku="AUTO-CAP-001",
        calculation=standard_calculation,
        cost_source="manual",
    )

    snapshot = (
        snapshot_repository
        .get_snapshot_by_line_item_id(
            "line-001"
        )
    )

    assert snapshot is not None

    assert (
        snapshot["shopify_line_item_id"]
        == "line-001"
    )

    assert (
        snapshot["shopify_order_id"]
        == "order-001"
    )

    assert snapshot["sku"] == "AUTO-CAP-001"
    assert snapshot["quantity"] == 1
    assert snapshot["currency_code"] == "USD"
    assert snapshot["unit_sale_price"] == "10.00"
    assert snapshot["unit_cost"] == "4.25"
    assert snapshot["line_revenue"] == "10.00"
    assert snapshot["line_cost"] == "4.25"

    assert (
        snapshot["estimated_gross_profit"]
        == "5.75"
    )

    assert (
        snapshot["gross_margin_percent"]
        == "57.50"
    )

    assert snapshot["cost_source"] == "manual"


def test_duplicate_line_item_does_not_create_second_snapshot(
    snapshot_repository,
    standard_calculation,
):
    first_created = (
        snapshot_repository.save_snapshot(
            shopify_line_item_id="line-001",
            shopify_order_id="order-001",
            shopify_variant_id="variant-001",
            sku="AUTO-CAP-001",
            calculation=standard_calculation,
            cost_source="manual",
        )
    )

    second_created = (
        snapshot_repository.save_snapshot(
            shopify_line_item_id="line-001",
            shopify_order_id="order-001",
            shopify_variant_id="variant-001",
            sku="AUTO-CAP-001",
            calculation=standard_calculation,
            cost_source="manual",
        )
    )

    assert first_created is True
    assert second_created is False

    assert (
        snapshot_repository.count_snapshots()
        == 1
    )


def test_existing_snapshot_is_immutable(
    snapshot_repository,
    standard_calculation,
):
    snapshot_repository.save_snapshot(
        shopify_line_item_id="line-001",
        shopify_order_id="order-001",
        shopify_variant_id="variant-001",
        sku="AUTO-CAP-001",
        calculation=standard_calculation,
        cost_source="manual",
    )

    changed_calculation = {
        **standard_calculation,
        "unit_cost": "9.00",
        "line_cost": "9.00",
        "estimated_gross_profit": "1.00",
        "gross_margin_percent": "10.00",
    }

    created_again = (
        snapshot_repository.save_snapshot(
            shopify_line_item_id="line-001",
            shopify_order_id="order-001",
            shopify_variant_id="variant-001",
            sku="AUTO-CAP-001",
            calculation=changed_calculation,
            cost_source="supplier",
        )
    )

    stored = (
        snapshot_repository
        .get_snapshot_by_line_item_id(
            "line-001"
        )
    )

    assert created_again is False

    assert (
        snapshot_repository.count_snapshots()
        == 1
    )

    # The original historical values must survive.
    assert stored["unit_cost"] == "4.25"

    assert (
        stored["estimated_gross_profit"]
        == "5.75"
    )

    assert (
        stored["gross_margin_percent"]
        == "57.50"
    )

    assert stored["cost_source"] == "manual"


def test_get_snapshots_for_order_returns_all_order_items(
    snapshot_repository,
    standard_calculation,
):
    snapshot_repository.save_snapshot(
        shopify_line_item_id="line-001",
        shopify_order_id="order-001",
        shopify_variant_id="variant-001",
        sku="AUTO-CAP-001",
        calculation=standard_calculation,
        cost_source="manual",
    )

    second_calculation = {
        **standard_calculation,
        "quantity": 2,
        "line_revenue": "20.00",
        "line_cost": "8.50",
        "estimated_gross_profit": "11.50",
    }

    snapshot_repository.save_snapshot(
        shopify_line_item_id="line-002",
        shopify_order_id="order-001",
        shopify_variant_id="variant-002",
        sku="AUTO-CAP-002",
        calculation=second_calculation,
        cost_source="supplier",
    )

    snapshot_repository.save_snapshot(
        shopify_line_item_id="line-003",
        shopify_order_id="order-002",
        shopify_variant_id="variant-003",
        sku="OTHER-001",
        calculation=standard_calculation,
        cost_source="manual",
    )

    snapshots = (
        snapshot_repository
        .get_snapshots_for_order(
            "order-001"
        )
    )

    assert len(snapshots) == 2

    assert [
        snapshot[
            "shopify_line_item_id"
        ]
        for snapshot in snapshots
    ] == [
        "line-001",
        "line-002",
    ]


def test_missing_snapshot_returns_none(
    snapshot_repository,
):
    result = (
        snapshot_repository
        .get_snapshot_by_line_item_id(
            "does-not-exist"
        )
    )

    assert result is None


def test_negative_profit_snapshot_can_be_persisted(
    snapshot_repository,
):
    loss_calculation = {
        "currency_code": "USD",
        "quantity": 1,
        "unit_sale_price": "0.00",
        "unit_cost": "4.25",
        "line_revenue": "0.00",
        "line_cost": "4.25",
        "estimated_gross_profit": "-4.25",
        "gross_margin_percent": None,
    }

    created = snapshot_repository.save_snapshot(
        shopify_line_item_id="loss-line-001",
        shopify_order_id="loss-order-001",
        shopify_variant_id="variant-loss-001",
        sku="LOSS-001",
        calculation=loss_calculation,
        cost_source="manual",
    )

    stored = (
        snapshot_repository
        .get_snapshot_by_line_item_id(
            "loss-line-001"
        )
    )

    assert created is True

    assert (
        stored["estimated_gross_profit"]
        == "-4.25"
    )

    assert stored["gross_margin_percent"] is None


@pytest.mark.parametrize(
    (
        "line_item_id",
        "order_id",
        "expected_message",
    ),
    [
        (
            "",
            "order-001",
            "shopify_line_item_id is required",
        ),
        (
            "line-001",
            "",
            "shopify_order_id is required",
        ),
    ],
)
def test_required_identifiers_are_validated(
    snapshot_repository,
    standard_calculation,
    line_item_id,
    order_id,
    expected_message,
):
    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        snapshot_repository.save_snapshot(
            shopify_line_item_id=line_item_id,
            shopify_order_id=order_id,
            shopify_variant_id="variant-001",
            sku="AUTO-CAP-001",
            calculation=standard_calculation,
            cost_source="manual",
        )


def test_missing_calculation_field_is_rejected(
    snapshot_repository,
    standard_calculation,
):
    incomplete_calculation = {
        key: value
        for key, value
        in standard_calculation.items()
        if key != "unit_cost"
    }

    with pytest.raises(
        ValueError,
        match=(
            "Profit calculation is missing "
            "required fields: unit_cost"
        ),
    ):
        snapshot_repository.save_snapshot(
            shopify_line_item_id="line-001",
            shopify_order_id="order-001",
            shopify_variant_id="variant-001",
            sku="AUTO-CAP-001",
            calculation=incomplete_calculation,
            cost_source="manual",
        )


@pytest.mark.parametrize(
    "invalid_source",
    [
        "estimated",
        "api",
        "unknown",
    ],
)
def test_invalid_cost_source_is_rejected(
    snapshot_repository,
    standard_calculation,
    invalid_source,
):
    with pytest.raises(
        ValueError,
        match=(
            "cost_source must be "
            "'manual' or 'supplier'"
        ),
    ):
        snapshot_repository.save_snapshot(
            shopify_line_item_id="line-001",
            shopify_order_id="order-001",
            shopify_variant_id="variant-001",
            sku="AUTO-CAP-001",
            calculation=standard_calculation,
            cost_source=invalid_source,
        )


def test_cost_source_is_normalized(
    snapshot_repository,
    standard_calculation,
):
    created = snapshot_repository.save_snapshot(
        shopify_line_item_id="line-001",
        shopify_order_id="order-001",
        shopify_variant_id="variant-001",
        sku="AUTO-CAP-001",
        calculation=standard_calculation,
        cost_source="  SUPPLIER  ",
    )

    stored = (
        snapshot_repository
        .get_snapshot_by_line_item_id(
            "line-001"
        )
    )

    assert created is True
    assert stored["cost_source"] == "supplier"
