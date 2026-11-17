from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from supplier.execution.models import SupplierExecutionError


INVENTORY_READBACK_QUERY = """
query SupplierInventoryReadback(
    $inventoryItemId: ID!,
    $locationId: ID!
) {
    inventoryItem(id: $inventoryItemId) {
        id
        sku
        tracked
        inventoryLevel(
            locationId: $locationId
            includeInactive: true
        ) {
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
"""


@dataclass(frozen=True)
class InventoryReadbackState:
    inventory_item_id: str
    sku: str | None
    tracked: bool
    location_id: str
    location_name: str
    location_active: bool
    level_active: bool
    available_quantity: int


class InventoryReadbackPort(Protocol):
    def read_available(
        self,
        *,
        inventory_item_id: str,
        location_id: str,
    ) -> InventoryReadbackState:
        ...


class ShopifyInventoryReadbackAdapter:
    """Read the live available quantity for one item/location."""

    def __init__(self, shopify_client) -> None:
        self._shopify_client = shopify_client

    def read_available(
        self,
        *,
        inventory_item_id: str,
        location_id: str,
    ) -> InventoryReadbackState:
        item_id = inventory_item_id.strip()
        loc_id = location_id.strip()

        if not item_id.startswith("gid://shopify/InventoryItem/"):
            raise SupplierExecutionError(
                "inventory_item_id must be a Shopify InventoryItem GID."
            )

        if not loc_id.startswith("gid://shopify/Location/"):
            raise SupplierExecutionError(
                "location_id must be a Shopify Location GID."
            )

        data = self._shopify_client.graphql(
            INVENTORY_READBACK_QUERY,
            {
                "inventoryItemId": item_id,
                "locationId": loc_id,
            },
        )

        item = data.get("inventoryItem") if isinstance(data, dict) else None
        if not isinstance(item, dict):
            raise SupplierExecutionError(
                "Shopify inventory item could not be read back."
            )

        if item.get("id") != item_id:
            raise SupplierExecutionError(
                "Shopify read-back inventory item ID does not match request."
            )

        level = item.get("inventoryLevel")
        if not isinstance(level, dict):
            raise SupplierExecutionError(
                "Inventory item is not stocked at the requested location."
            )

        location = level.get("location") or {}
        returned_location_id = (
            location.get("id") if isinstance(location, dict) else None
        )
        if returned_location_id != loc_id:
            raise SupplierExecutionError(
                "Shopify read-back location ID does not match request."
            )

        available = None
        for quantity in level.get("quantities") or []:
            if not isinstance(quantity, dict):
                continue
            if quantity.get("name") != "available":
                continue

            value = quantity.get("quantity")
            if isinstance(value, bool) or not isinstance(value, int):
                raise SupplierExecutionError(
                    "Shopify returned an invalid available quantity."
                )
            available = value
            break

        if available is None:
            raise SupplierExecutionError(
                "Shopify did not return an available inventory quantity."
            )

        location_name = (
            location.get("name") if isinstance(location, dict) else None
        )
        if not isinstance(location_name, str) or not location_name.strip():
            raise SupplierExecutionError(
                "Shopify read-back location has no name."
            )

        sku = item.get("sku")
        if sku is not None and not isinstance(sku, str):
            sku = str(sku)

        return InventoryReadbackState(
            inventory_item_id=item_id,
            sku=sku.strip() if isinstance(sku, str) else None,
            tracked=bool(item.get("tracked")),
            location_id=loc_id,
            location_name=location_name.strip(),
            location_active=bool(location.get("isActive")),
            level_active=bool(level.get("isActive")),
            available_quantity=available,
        )
