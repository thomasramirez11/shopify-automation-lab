import sqlite3
from contextlib import contextmanager

import pytest

from supplier.execution.models import (
    InventoryMutation,
    SupplierExecutionError,
)
from supplier.execution.shopify_adapter import (
    LiveShopifyWriteDisabledError,
    SQLiteInventoryTargetResolver,
    ShopifyInventoryMutationAdapter,
    ShopifyInventoryTarget,
    ShopifyInventoryTargetError,
    build_inventory_idempotency_key,
    build_inventory_set_variables,
)
from supplier.execution.safety import (
    live_writes_enabled_from_environment,
)


VARIANT_ID = "gid://shopify/ProductVariant/111"
INVENTORY_ITEM_ID = "gid://shopify/InventoryItem/222"
LOCATION_ID = "gid://shopify/Location/333"


class RecordingClient:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {
            "inventorySetQuantities": {
                "inventoryAdjustmentGroup": {
                    "reason": "Inventory correction",
                    "changes": [],
                },
                "userErrors": [],
            }
        }

    def graphql(self, query, variables):
        self.calls.append((query, variables))
        return self.response


class StaticResolver:
    def __init__(self, target=None):
        self.target = target or ShopifyInventoryTarget(
            inventory_item_id=INVENTORY_ITEM_ID,
            location_id=LOCATION_ID,
        )
        self.calls = 0

    def resolve(self, shopify_variant_id):
        self.calls += 1
        return self.target


def mutation(*, quantity=25, expected=1):
    return InventoryMutation(
        shopify_variant_id=VARIANT_ID,
        shopify_sku="AUTO-CAP-001",
        inventory_quantity=quantity,
        expected_current_quantity=expected,
    )


def test_live_write_environment_defaults_false(monkeypatch):
    monkeypatch.delenv(
        "SUPPLIER_SYNC_LIVE_WRITES",
        raising=False,
    )

    assert live_writes_enabled_from_environment() is False


def test_live_write_environment_accepts_true(monkeypatch):
    monkeypatch.setenv(
        "SUPPLIER_SYNC_LIVE_WRITES",
        "true",
    )

    assert live_writes_enabled_from_environment() is True


def test_live_write_environment_rejects_ambiguous_value(monkeypatch):
    monkeypatch.setenv(
        "SUPPLIER_SYNC_LIVE_WRITES",
        "maybe",
    )

    with pytest.raises(
        SupplierExecutionError,
        match="explicit boolean",
    ):
        live_writes_enabled_from_environment()


def test_disabled_adapter_blocks_before_graphql_or_resolution():
    client = RecordingClient()
    resolver = StaticResolver()

    adapter = ShopifyInventoryMutationAdapter(
        shopify_client=client,
        target_resolver=resolver,
    )

    with pytest.raises(
        LiveShopifyWriteDisabledError,
        match="disabled",
    ):
        adapter.set_inventory(mutation())

    assert client.calls == []
    assert resolver.calls == 0


def test_variables_include_compare_and_swap_quantity():
    target = ShopifyInventoryTarget(
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
    )

    variables = build_inventory_set_variables(
        mutation=mutation(quantity=25, expected=1),
        target=target,
    )

    quantity_input = variables["input"]["quantities"][0]

    assert quantity_input["changeFromQuantity"] == 1
    assert quantity_input["quantity"] == 25


def test_variables_include_location_and_inventory_item():
    target = ShopifyInventoryTarget(
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
    )

    variables = build_inventory_set_variables(
        mutation=mutation(),
        target=target,
    )

    quantity_input = variables["input"]["quantities"][0]

    assert quantity_input["inventoryItemId"] == INVENTORY_ITEM_ID
    assert quantity_input["locationId"] == LOCATION_ID


def test_idempotency_key_is_stable_for_same_mutation():
    target = ShopifyInventoryTarget(
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
    )

    first = build_inventory_idempotency_key(
        mutation=mutation(),
        target=target,
    )
    second = build_inventory_idempotency_key(
        mutation=mutation(),
        target=target,
    )

    assert first == second


def test_idempotency_key_changes_when_quantity_changes():
    target = ShopifyInventoryTarget(
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
    )

    first = build_inventory_idempotency_key(
        mutation=mutation(quantity=25),
        target=target,
    )
    second = build_inventory_idempotency_key(
        mutation=mutation(quantity=26),
        target=target,
    )

    assert first != second


def test_enabled_adapter_calls_graphql_and_reports_success():
    client = RecordingClient()
    resolver = StaticResolver()

    adapter = ShopifyInventoryMutationAdapter(
        shopify_client=client,
        target_resolver=resolver,
        live_writes_enabled=True,
    )

    result = adapter.set_inventory(mutation())

    assert result.applied is True
    assert len(client.calls) == 1
    assert resolver.calls == 1


def test_shopify_user_error_is_raised():
    client = RecordingClient(
        response={
            "inventorySetQuantities": {
                "inventoryAdjustmentGroup": None,
                "userErrors": [
                    {
                        "code": "CHANGE_FROM_QUANTITY_STALE",
                        "field": ["input"],
                        "message": "Inventory changed.",
                    }
                ],
            }
        }
    )

    adapter = ShopifyInventoryMutationAdapter(
        shopify_client=client,
        target_resolver=StaticResolver(),
        live_writes_enabled=True,
    )

    with pytest.raises(
        SupplierExecutionError,
        match="CHANGE_FROM_QUANTITY_STALE",
    ):
        adapter.set_inventory(mutation())


def test_real_adapter_requires_expected_current_quantity():
    adapter = ShopifyInventoryMutationAdapter(
        shopify_client=RecordingClient(),
        target_resolver=StaticResolver(),
        live_writes_enabled=True,
    )

    with pytest.raises(
        SupplierExecutionError,
        match="expected_current_quantity",
    ):
        adapter.set_inventory(
            InventoryMutation(
                shopify_variant_id=VARIANT_ID,
                shopify_sku="AUTO-CAP-001",
                inventory_quantity=25,
            )
        )


def test_invalid_location_gid_is_rejected():
    with pytest.raises(
        ShopifyInventoryTargetError,
        match="Location GID",
    ):
        ShopifyInventoryTarget(
            inventory_item_id=INVENTORY_ITEM_ID,
            location_id="123",
        )


def build_sqlite_factory(
    *,
    inventory_item_id=INVENTORY_ITEM_ID,
    include_variant=True,
):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    connection.execute(
        """
        CREATE TABLE variants (
            shopify_variant_id TEXT PRIMARY KEY,
            inventory_item_id TEXT
        );
        """
    )

    if include_variant:
        connection.execute(
            """
            INSERT INTO variants (
                shopify_variant_id,
                inventory_item_id
            )
            VALUES (?, ?);
            """,
            (
                VARIANT_ID,
                inventory_item_id,
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


def test_sqlite_target_resolver_uses_persisted_inventory_item():
    resolver = SQLiteInventoryTargetResolver(
        location_id=LOCATION_ID,
        connection_factory=build_sqlite_factory(),
    )

    target = resolver.resolve(VARIANT_ID)

    assert target is not None
    assert target.inventory_item_id == INVENTORY_ITEM_ID
    assert target.location_id == LOCATION_ID


def test_sqlite_target_resolver_returns_none_for_unknown_variant():
    resolver = SQLiteInventoryTargetResolver(
        location_id=LOCATION_ID,
        connection_factory=build_sqlite_factory(
            include_variant=False
        ),
    )

    assert resolver.resolve(VARIANT_ID) is None


def test_expected_current_quantity_validation():
    with pytest.raises(
        SupplierExecutionError,
        match="expected_current_quantity cannot be negative",
    ):
        mutation(expected=-1)
