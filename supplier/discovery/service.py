from __future__ import annotations

from collections.abc import Iterable

from supplier.discovery.models import (
    ShopifyInventoryDiscoveryReport,
    ShopifyInventoryLevelState,
    ShopifyLocationState,
    SupplierDiscoveryError,
)


ACCESS_SCOPES_QUERY = """
query SupplierDiscoveryAccessScopes {
    currentAppInstallation {
        accessScopes {
            handle
        }
    }
}
"""


LOCATIONS_QUERY = """
query SupplierDiscoveryLocations($first: Int!) {
    locations(
        first: $first
        includeInactive: false
        includeLegacy: false
    ) {
        nodes {
            id
            name
            isActive
            fulfillsOnlineOrders
            hasActiveInventory
        }
    }
}
"""


INVENTORY_ITEM_QUERY = """
query SupplierDiscoveryInventoryItem($id: ID!, $first: Int!) {
    inventoryItem(id: $id) {
        id
        sku
        tracked
        inventoryLevels(first: $first) {
            nodes {
                id
                isActive
                location {
                    id
                    name
                    isActive
                }
                quantities(names: ["available"]) {
                    name
                    quantity
                }
            }
        }
    }
}
"""


class ShopifyInventoryDiscoveryService:
    """
    Perform read-only Shopify discovery needed before enabling V2 writes.

    The service contains only GraphQL queries. No mutation is defined or sent.
    """

    def __init__(
        self,
        shopify_client,
        *,
        page_size: int = 50,
    ) -> None:
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or page_size <= 0
        ):
            raise SupplierDiscoveryError(
                "page_size must be a positive integer."
            )

        self._client = shopify_client
        self._page_size = page_size

    def discover(
        self,
        inventory_item_ids: Iterable[str],
    ) -> ShopifyInventoryDiscoveryReport:
        normalized_ids = (
            self._normalize_inventory_item_ids(
                inventory_item_ids
            )
        )

        granted_scopes = (
            self._load_granted_scopes()
        )

        locations = (
            self._load_locations()
        )

        inventory_levels = []
        missing_inventory_item_ids = []

        for inventory_item_id in normalized_ids:
            item = self._load_inventory_item(
                inventory_item_id
            )

            if item is None:
                missing_inventory_item_ids.append(
                    inventory_item_id
                )
                continue

            inventory_levels.extend(
                self._normalize_inventory_levels(
                    item
                )
            )

        return ShopifyInventoryDiscoveryReport(
            granted_scopes=(
                tuple(
                    sorted(
                        granted_scopes
                    )
                )
            ),
            locations=tuple(
                locations
            ),
            inventory_levels=tuple(
                inventory_levels
            ),
            missing_inventory_item_ids=tuple(
                missing_inventory_item_ids
            ),
        )

    def _load_granted_scopes(
        self,
    ) -> set[str]:
        data = self._client.graphql(
            ACCESS_SCOPES_QUERY,
            {},
        )

        installation = (
            data.get(
                "currentAppInstallation"
            )
            if isinstance(data, dict)
            else None
        )

        if not isinstance(
            installation,
            dict,
        ):
            raise SupplierDiscoveryError(
                "Shopify did not return currentAppInstallation."
            )

        scopes = (
            installation.get(
                "accessScopes"
            )
            or []
        )

        handles = set()

        for scope in scopes:
            if not isinstance(scope, dict):
                continue

            handle = scope.get(
                "handle"
            )

            if (
                isinstance(handle, str)
                and handle.strip()
            ):
                handles.add(
                    handle.strip()
                )

        return handles

    def _load_locations(
        self,
    ) -> list[ShopifyLocationState]:
        data = self._client.graphql(
            LOCATIONS_QUERY,
            {
                "first": (
                    self._page_size
                )
            },
        )

        connection = (
            data.get("locations")
            if isinstance(data, dict)
            else None
        )

        if not isinstance(
            connection,
            dict,
        ):
            raise SupplierDiscoveryError(
                "Shopify did not return locations."
            )

        nodes = (
            connection.get("nodes")
            or []
        )

        locations = []

        for node in nodes:
            if not isinstance(node, dict):
                continue

            location_id = node.get("id")
            name = node.get("name")

            if (
                not isinstance(
                    location_id,
                    str,
                )
                or not location_id.startswith(
                    "gid://shopify/Location/"
                )
            ):
                raise SupplierDiscoveryError(
                    "Shopify returned an invalid location ID."
                )

            if (
                not isinstance(name, str)
                or not name.strip()
            ):
                raise SupplierDiscoveryError(
                    "Shopify returned a location without a name."
                )

            locations.append(
                ShopifyLocationState(
                    location_id=location_id,
                    name=name.strip(),
                    is_active=bool(
                        node.get(
                            "isActive"
                        )
                    ),
                    fulfills_online_orders=bool(
                        node.get(
                            "fulfillsOnlineOrders"
                        )
                    ),
                    has_active_inventory=bool(
                        node.get(
                            "hasActiveInventory"
                        )
                    ),
                )
            )

        return locations

    def _load_inventory_item(
        self,
        inventory_item_id: str,
    ) -> dict | None:
        data = self._client.graphql(
            INVENTORY_ITEM_QUERY,
            {
                "id": inventory_item_id,
                "first": (
                    self._page_size
                ),
            },
        )

        if not isinstance(data, dict):
            raise SupplierDiscoveryError(
                "Shopify returned an invalid inventory-item response."
            )

        item = data.get(
            "inventoryItem"
        )

        if item is None:
            return None

        if not isinstance(item, dict):
            raise SupplierDiscoveryError(
                "Shopify returned an invalid inventory item."
            )

        return item

    def _normalize_inventory_levels(
        self,
        item: dict,
    ) -> list[ShopifyInventoryLevelState]:
        inventory_item_id = (
            item.get("id")
        )

        if (
            not isinstance(
                inventory_item_id,
                str,
            )
            or not inventory_item_id.startswith(
                "gid://shopify/InventoryItem/"
            )
        ):
            raise SupplierDiscoveryError(
                "Shopify returned an invalid inventory item ID."
            )

        sku = item.get("sku")
        if (
            sku is not None
            and not isinstance(sku, str)
        ):
            sku = str(sku)

        tracked = bool(
            item.get("tracked")
        )

        levels_connection = (
            item.get(
                "inventoryLevels"
            )
            or {}
        )

        nodes = (
            levels_connection.get(
                "nodes"
            )
            if isinstance(
                levels_connection,
                dict,
            )
            else []
        ) or []

        results = []

        for node in nodes:
            if not isinstance(node, dict):
                continue

            location = (
                node.get("location")
                or {}
            )

            location_id = (
                location.get("id")
                if isinstance(
                    location,
                    dict,
                )
                else None
            )

            location_name = (
                location.get("name")
                if isinstance(
                    location,
                    dict,
                )
                else None
            )

            if (
                not isinstance(
                    location_id,
                    str,
                )
                or not location_id.startswith(
                    "gid://shopify/Location/"
                )
            ):
                raise SupplierDiscoveryError(
                    "Inventory level returned an invalid location ID."
                )

            if (
                not isinstance(
                    location_name,
                    str,
                )
                or not location_name.strip()
            ):
                raise SupplierDiscoveryError(
                    "Inventory level returned a location without a name."
                )

            available_quantity = (
                self._available_quantity(
                    node.get(
                        "quantities"
                    )
                    or []
                )
            )

            results.append(
                ShopifyInventoryLevelState(
                    inventory_item_id=(
                        inventory_item_id
                    ),
                    sku=(
                        sku.strip()
                        if isinstance(
                            sku,
                            str,
                        )
                        else None
                    ),
                    tracked=tracked,
                    location_id=(
                        location_id
                    ),
                    location_name=(
                        location_name.strip()
                    ),
                    location_active=bool(
                        location.get(
                            "isActive"
                        )
                    ),
                    level_active=bool(
                        node.get(
                            "isActive"
                        )
                    ),
                    available_quantity=(
                        available_quantity
                    ),
                )
            )

        return results

    def _available_quantity(
        self,
        quantities,
    ) -> int | None:
        for quantity in quantities:
            if not isinstance(
                quantity,
                dict,
            ):
                continue

            if quantity.get(
                "name"
            ) != "available":
                continue

            value = quantity.get(
                "quantity"
            )

            if (
                isinstance(value, bool)
                or not isinstance(
                    value,
                    int,
                )
            ):
                raise SupplierDiscoveryError(
                    "Shopify returned an invalid available quantity."
                )

            return value

        return None

    def _normalize_inventory_item_ids(
        self,
        inventory_item_ids: Iterable[str],
    ) -> tuple[str, ...]:
        normalized = []
        seen = set()

        for inventory_item_id in inventory_item_ids:
            if not isinstance(
                inventory_item_id,
                str,
            ):
                raise SupplierDiscoveryError(
                    "inventory_item_id must be a string."
                )

            item_id = (
                inventory_item_id.strip()
            )

            if not item_id.startswith(
                "gid://shopify/InventoryItem/"
            ):
                raise SupplierDiscoveryError(
                    "inventory_item_id must be a Shopify InventoryItem GID."
                )

            if item_id in seen:
                continue

            seen.add(item_id)
            normalized.append(
                item_id
            )

        return tuple(
            normalized
        )
