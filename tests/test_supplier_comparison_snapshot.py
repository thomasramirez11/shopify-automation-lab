import sqlite3
from contextlib import contextmanager
from decimal import Decimal

import pytest

from supplier.comparison.snapshot import (
    SQLiteShopifyComparisonSnapshotAdapter,
    ShopifySnapshotError,
)


VARIANT_ID = (
    "gid://shopify/ProductVariant/56166258147700"
)


def build_connection_factory(
    *,
    variant_exists=True,
    sku="AUTO-Cap-001",
    inventory_quantity=1,
    unit_cost="4.25",
    currency_code="USD",
    cost_source="manual",
):
    connection = sqlite3.connect(
        ":memory:"
    )

    connection.row_factory = (
        sqlite3.Row
    )

    connection.executescript(
        """
        CREATE TABLE variants (
            shopify_variant_id TEXT PRIMARY KEY,
            sku TEXT,
            inventory_quantity INTEGER
        );

        CREATE TABLE variant_costs (
            shopify_variant_id TEXT PRIMARY KEY,
            unit_cost TEXT NOT NULL,
            currency_code TEXT NOT NULL,
            cost_source TEXT NOT NULL
        );
        """
    )

    if variant_exists:
        connection.execute(
            """
            INSERT INTO variants (
                shopify_variant_id,
                sku,
                inventory_quantity
            )
            VALUES (?, ?, ?);
            """,
            (
                VARIANT_ID,
                sku,
                inventory_quantity,
            ),
        )

        if unit_cost is not None:
            connection.execute(
                """
                INSERT INTO variant_costs (
                    shopify_variant_id,
                    unit_cost,
                    currency_code,
                    cost_source
                )
                VALUES (?, ?, ?, ?);
                """,
                (
                    VARIANT_ID,
                    unit_cost,
                    currency_code,
                    cost_source,
                ),
            )

    connection.commit()

    @contextmanager
    def factory():
        try:
            yield connection
        finally:
            pass

    return factory


def test_snapshot_reads_variant_and_cost():
    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=(
                build_connection_factory()
            )
        )
    )

    snapshot = (
        adapter.get_snapshot(
            VARIANT_ID
        )
    )

    assert snapshot is not None
    assert (
        snapshot.shopify_variant.shopify_sku
        == "AUTO-Cap-001"
    )
    assert (
        snapshot.shopify_variant.inventory_quantity
        == 1
    )
    assert (
        snapshot.stored_cost
        == Decimal("4.25")
    )
    assert (
        snapshot.cost_currency
        == "USD"
    )
    assert (
        snapshot.cost_source
        == "manual"
    )


def test_snapshot_returns_none_when_variant_missing():
    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=(
                build_connection_factory(
                    variant_exists=False
                )
            )
        )
    )

    assert (
        adapter.get_snapshot(
            VARIANT_ID
        )
        is None
    )


def test_snapshot_allows_variant_without_cost():
    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=(
                build_connection_factory(
                    unit_cost=None
                )
            )
        )
    )

    snapshot = (
        adapter.get_snapshot(
            VARIANT_ID
        )
    )

    assert snapshot is not None
    assert snapshot.stored_cost is None
    assert snapshot.cost_currency is None
    assert snapshot.cost_source is None


def test_snapshot_rejects_empty_variant_id():
    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=(
                build_connection_factory()
            )
        )
    )

    with pytest.raises(
        ShopifySnapshotError,
        match="shopify_variant_id cannot be empty",
    ):
        adapter.get_snapshot(
            "   "
        )


def test_snapshot_rejects_missing_sku():
    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=(
                build_connection_factory(
                    sku=None
                )
            )
        )
    )

    with pytest.raises(
        ShopifySnapshotError,
        match="must have a non-empty SKU",
    ):
        adapter.get_snapshot(
            VARIANT_ID
        )


def test_snapshot_rejects_blank_sku():
    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=(
                build_connection_factory(
                    sku="   "
                )
            )
        )
    )

    with pytest.raises(
        ShopifySnapshotError,
        match="must have a non-empty SKU",
    ):
        adapter.get_snapshot(
            VARIANT_ID
        )


def test_snapshot_rejects_missing_inventory():
    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=(
                build_connection_factory(
                    inventory_quantity=None
                )
            )
        )
    )

    with pytest.raises(
        ShopifySnapshotError,
        match="must have inventory_quantity",
    ):
        adapter.get_snapshot(
            VARIANT_ID
        )


def test_snapshot_rejects_negative_inventory():
    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=(
                build_connection_factory(
                    inventory_quantity=-1
                )
            )
        )
    )

    with pytest.raises(
        ShopifySnapshotError,
        match="inventory_quantity cannot be negative",
    ):
        adapter.get_snapshot(
            VARIANT_ID
        )


def test_snapshot_rejects_invalid_cost():
    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=(
                build_connection_factory(
                    unit_cost="bad-money"
                )
            )
        )
    )

    with pytest.raises(
        ShopifySnapshotError,
        match="unit_cost must be a valid decimal",
    ):
        adapter.get_snapshot(
            VARIANT_ID
        )


def test_snapshot_rejects_negative_cost():
    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=(
                build_connection_factory(
                    unit_cost="-0.01"
                )
            )
        )
    )

    with pytest.raises(
        ShopifySnapshotError,
        match="unit_cost cannot be negative",
    ):
        adapter.get_snapshot(
            VARIANT_ID
        )


def test_snapshot_trims_optional_cost_metadata():
    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=(
                build_connection_factory(
                    currency_code=" USD ",
                    cost_source=" manual ",
                )
            )
        )
    )

    snapshot = (
        adapter.get_snapshot(
            VARIANT_ID
        )
    )

    assert snapshot is not None
    assert (
        snapshot.cost_currency
        == "USD"
    )
    assert (
        snapshot.cost_source
        == "manual"
    )


def test_snapshot_query_is_read_only():
    factory = (
        build_connection_factory()
    )

    adapter = (
        SQLiteShopifyComparisonSnapshotAdapter(
            connection_factory=factory
        )
    )

    adapter.get_snapshot(
        VARIANT_ID
    )

    with factory() as connection:
        variant_count = (
            connection.execute(
                "SELECT COUNT(*) FROM variants;"
            )
            .fetchone()[0]
        )

        cost_count = (
            connection.execute(
                "SELECT COUNT(*) FROM variant_costs;"
            )
            .fetchone()[0]
        )

    assert variant_count == 1
    assert cost_count == 1
