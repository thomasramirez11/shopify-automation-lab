import pytest

from supplier.discovery.models import (
    SupplierDiscoveryError,
)
from supplier.discovery.service import (
    ACCESS_SCOPES_QUERY,
    INVENTORY_ITEM_QUERY,
    LOCATIONS_QUERY,
    ShopifyInventoryDiscoveryService,
)


ITEM_1 = (
    "gid://shopify/InventoryItem/111"
)

ITEM_2 = (
    "gid://shopify/InventoryItem/222"
)

LOCATION_1 = (
    "gid://shopify/Location/333"
)

LOCATION_2 = (
    "gid://shopify/Location/444"
)


class FakeClient:
    def __init__(
        self,
        *,
        scopes=None,
        locations=None,
        items=None,
    ):
        self.scopes = scopes or [
            "read_inventory",
            "write_inventory",
        ]

        self.locations = (
            locations
            if locations is not None
            else [
                {
                    "id": LOCATION_1,
                    "name": "Main Warehouse",
                    "isActive": True,
                    "fulfillsOnlineOrders": True,
                    "hasActiveInventory": True,
                }
            ]
        )

        self.items = (
            items
            if items is not None
            else {
                ITEM_1: {
                    "id": ITEM_1,
                    "sku": "AUTO-CAP-001",
                    "tracked": True,
                    "inventoryLevels": {
                        "nodes": [
                            {
                                "id": (
                                    "gid://shopify/InventoryLevel/1"
                                ),
                                "isActive": True,
                                "location": {
                                    "id": LOCATION_1,
                                    "name": "Main Warehouse",
                                    "isActive": True,
                                },
                                "quantities": [
                                    {
                                        "name": "available",
                                        "quantity": 1,
                                    }
                                ],
                            }
                        ]
                    },
                }
            }
        )

        self.calls = []

    def graphql(
        self,
        query,
        variables,
    ):
        self.calls.append(
            (
                query,
                variables,
            )
        )

        if query == ACCESS_SCOPES_QUERY:
            return {
                "currentAppInstallation": {
                    "accessScopes": [
                        {
                            "handle": scope
                        }
                        for scope in self.scopes
                    ]
                }
            }

        if query == LOCATIONS_QUERY:
            return {
                "locations": {
                    "nodes": (
                        self.locations
                    )
                }
            }

        if query == INVENTORY_ITEM_QUERY:
            return {
                "inventoryItem": (
                    self.items.get(
                        variables["id"]
                    )
                )
            }

        raise AssertionError(
            "Unexpected GraphQL document."
        )


def test_discovery_reads_inventory_permissions():
    service = (
        ShopifyInventoryDiscoveryService(
            FakeClient()
        )
    )

    report = service.discover(
        [ITEM_1]
    )

    assert (
        report.has_read_inventory
        is True
    )
    assert (
        report.has_write_inventory
        is True
    )
    assert (
        report.permission_ready_for_live_inventory
        is True
    )


def test_missing_write_inventory_is_not_permission_ready():
    service = (
        ShopifyInventoryDiscoveryService(
            FakeClient(
                scopes=[
                    "read_inventory"
                ]
            )
        )
    )

    report = service.discover(
        [ITEM_1]
    )

    assert (
        report.permission_ready_for_live_inventory
        is False
    )


def test_locations_are_normalized():
    report = (
        ShopifyInventoryDiscoveryService(
            FakeClient()
        )
        .discover(
            [ITEM_1]
        )
    )

    location = (
        report.locations[0]
    )

    assert (
        location.location_id
        == LOCATION_1
    )
    assert (
        location.name
        == "Main Warehouse"
    )
    assert (
        location.is_active
        is True
    )


def test_inventory_level_is_normalized():
    report = (
        ShopifyInventoryDiscoveryService(
            FakeClient()
        )
        .discover(
            [ITEM_1]
        )
    )

    level = (
        report.inventory_levels[0]
    )

    assert (
        level.inventory_item_id
        == ITEM_1
    )
    assert (
        level.location_id
        == LOCATION_1
    )
    assert (
        level.available_quantity
        == 1
    )
    assert (
        level.tracked
        is True
    )


def test_unknown_inventory_item_is_reported_missing():
    report = (
        ShopifyInventoryDiscoveryService(
            FakeClient()
        )
        .discover(
            [
                ITEM_1,
                ITEM_2,
            ]
        )
    )

    assert (
        report.missing_inventory_item_ids
        == (
            ITEM_2,
        )
    )


def test_duplicate_inventory_item_ids_are_queried_once():
    client = FakeClient()

    ShopifyInventoryDiscoveryService(
        client
    ).discover(
        [
            ITEM_1,
            ITEM_1,
        ]
    )

    item_calls = [
        call
        for call in client.calls
        if call[0]
        == INVENTORY_ITEM_QUERY
    ]

    assert len(
        item_calls
    ) == 1


def test_active_levels_for_location_filters_inactive_levels():
    items = {
        ITEM_1: {
            "id": ITEM_1,
            "sku": "AUTO-CAP-001",
            "tracked": True,
            "inventoryLevels": {
                "nodes": [
                    {
                        "id": "level-1",
                        "isActive": True,
                        "location": {
                            "id": LOCATION_1,
                            "name": "Main Warehouse",
                            "isActive": True,
                        },
                        "quantities": [
                            {
                                "name": "available",
                                "quantity": 1,
                            }
                        ],
                    },
                    {
                        "id": "level-2",
                        "isActive": False,
                        "location": {
                            "id": LOCATION_2,
                            "name": "Old Warehouse",
                            "isActive": True,
                        },
                        "quantities": [
                            {
                                "name": "available",
                                "quantity": 5,
                            }
                        ],
                    },
                ]
            },
        }
    }

    report = (
        ShopifyInventoryDiscoveryService(
            FakeClient(
                items=items
            )
        )
        .discover(
            [ITEM_1]
        )
    )

    levels = (
        report.active_levels_for_location(
            LOCATION_1
        )
    )

    assert len(levels) == 1
    assert (
        levels[0].location_id
        == LOCATION_1
    )


def test_available_quantity_can_be_zero():
    items = {
        ITEM_1: {
            "id": ITEM_1,
            "sku": "AUTO-CAP-001",
            "tracked": True,
            "inventoryLevels": {
                "nodes": [
                    {
                        "id": "level-1",
                        "isActive": True,
                        "location": {
                            "id": LOCATION_1,
                            "name": "Main Warehouse",
                            "isActive": True,
                        },
                        "quantities": [
                            {
                                "name": "available",
                                "quantity": 0,
                            }
                        ],
                    }
                ]
            },
        }
    }

    report = (
        ShopifyInventoryDiscoveryService(
            FakeClient(
                items=items
            )
        )
        .discover(
            [ITEM_1]
        )
    )

    assert (
        report.inventory_levels[0]
        .available_quantity
        == 0
    )


def test_missing_available_quantity_becomes_none():
    items = {
        ITEM_1: {
            "id": ITEM_1,
            "sku": "AUTO-CAP-001",
            "tracked": True,
            "inventoryLevels": {
                "nodes": [
                    {
                        "id": "level-1",
                        "isActive": True,
                        "location": {
                            "id": LOCATION_1,
                            "name": "Main Warehouse",
                            "isActive": True,
                        },
                        "quantities": [],
                    }
                ]
            },
        }
    }

    report = (
        ShopifyInventoryDiscoveryService(
            FakeClient(
                items=items
            )
        )
        .discover(
            [ITEM_1]
        )
    )

    assert (
        report.inventory_levels[0]
        .available_quantity
        is None
    )


def test_invalid_inventory_item_gid_is_rejected():
    service = (
        ShopifyInventoryDiscoveryService(
            FakeClient()
        )
    )

    with pytest.raises(
        SupplierDiscoveryError,
        match="InventoryItem GID",
    ):
        service.discover(
            ["123"]
        )


def test_invalid_page_size_is_rejected():
    with pytest.raises(
        SupplierDiscoveryError,
        match="positive integer",
    ):
        ShopifyInventoryDiscoveryService(
            FakeClient(),
            page_size=0,
        )


def test_invalid_location_gid_is_rejected():
    client = FakeClient(
        locations=[
            {
                "id": "123",
                "name": "Bad",
                "isActive": True,
                "fulfillsOnlineOrders": True,
                "hasActiveInventory": True,
            }
        ]
    )

    with pytest.raises(
        SupplierDiscoveryError,
        match="invalid location ID",
    ):
        ShopifyInventoryDiscoveryService(
            client
        ).discover(
            [ITEM_1]
        )


def test_invalid_available_quantity_is_rejected():
    items = {
        ITEM_1: {
            "id": ITEM_1,
            "sku": "AUTO-CAP-001",
            "tracked": True,
            "inventoryLevels": {
                "nodes": [
                    {
                        "id": "level-1",
                        "isActive": True,
                        "location": {
                            "id": LOCATION_1,
                            "name": "Main Warehouse",
                            "isActive": True,
                        },
                        "quantities": [
                            {
                                "name": "available",
                                "quantity": "1",
                            }
                        ],
                    }
                ]
            },
        }
    }

    with pytest.raises(
        SupplierDiscoveryError,
        match="invalid available quantity",
    ):
        ShopifyInventoryDiscoveryService(
            FakeClient(
                items=items
            )
        ).discover(
            [ITEM_1]
        )


def test_discovery_queries_are_read_only():
    documents = (
        ACCESS_SCOPES_QUERY,
        LOCATIONS_QUERY,
        INVENTORY_ITEM_QUERY,
    )

    for document in documents:
        normalized = (
            document
            .strip()
            .lower()
        )

        assert normalized.startswith(
            "query"
        )
        assert "mutation " not in (
            normalized
        )


def test_discovery_call_count_matches_expected_queries():
    client = FakeClient(
        items={
            ITEM_1: FakeClient().items[
                ITEM_1
            ],
            ITEM_2: {
                "id": ITEM_2,
                "sku": "AUTO-SHIRT-L",
                "tracked": True,
                "inventoryLevels": {
                    "nodes": []
                },
            },
        }
    )

    ShopifyInventoryDiscoveryService(
        client
    ).discover(
        [
            ITEM_1,
            ITEM_2,
        ]
    )

    # 1 access-scope query + 1 locations query + 2 inventory-item queries.
    assert len(
        client.calls
    ) == 4


def test_active_location_count():
    client = FakeClient(
        locations=[
            {
                "id": LOCATION_1,
                "name": "Main",
                "isActive": True,
                "fulfillsOnlineOrders": True,
                "hasActiveInventory": True,
            },
            {
                "id": LOCATION_2,
                "name": "Secondary",
                "isActive": False,
                "fulfillsOnlineOrders": False,
                "hasActiveInventory": False,
            },
        ]
    )

    report = (
        ShopifyInventoryDiscoveryService(
            client
        )
        .discover(
            [ITEM_1]
        )
    )

    assert (
        report.active_location_count
        == 1
    )
