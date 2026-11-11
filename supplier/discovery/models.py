from __future__ import annotations

from dataclasses import dataclass


class SupplierDiscoveryError(RuntimeError):
    """Raised when Shopify discovery data is invalid or incomplete."""


@dataclass(frozen=True)
class ShopifyLocationState:
    location_id: str
    name: str
    is_active: bool
    fulfills_online_orders: bool
    has_active_inventory: bool


@dataclass(frozen=True)
class ShopifyInventoryLevelState:
    inventory_item_id: str
    sku: str | None
    tracked: bool
    location_id: str
    location_name: str
    location_active: bool
    level_active: bool
    available_quantity: int | None


@dataclass(frozen=True)
class ShopifyInventoryDiscoveryReport:
    granted_scopes: tuple[str, ...]
    locations: tuple[ShopifyLocationState, ...]
    inventory_levels: tuple[ShopifyInventoryLevelState, ...]
    missing_inventory_item_ids: tuple[str, ...]

    @property
    def has_read_inventory(self) -> bool:
        return "read_inventory" in self.granted_scopes

    @property
    def has_write_inventory(self) -> bool:
        return "write_inventory" in self.granted_scopes

    @property
    def permission_ready_for_live_inventory(self) -> bool:
        return (
            self.has_read_inventory
            and self.has_write_inventory
        )

    @property
    def active_location_count(self) -> int:
        return sum(
            1
            for location in self.locations
            if location.is_active
        )

    def active_levels_for_location(
        self,
        location_id: str,
    ) -> tuple[ShopifyInventoryLevelState, ...]:
        normalized = location_id.strip()

        return tuple(
            level
            for level in self.inventory_levels
            if (
                level.location_id == normalized
                and level.location_active
                and level.level_active
            )
        )
