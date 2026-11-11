from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


from config.settings import (  # noqa: E402
    SHOPIFY_API_VERSION,
    SHOPIFY_CLIENT_ID,
    SHOPIFY_CLIENT_SECRET,
    SHOPIFY_STORE_DOMAIN,
)
from database.connection import get_db_connection  # noqa: E402
from shopify.client import ShopifyClient  # noqa: E402
from supplier.discovery.service import (  # noqa: E402
    ShopifyInventoryDiscoveryService,
)


def load_mapped_inventory_items() -> list[dict]:
    """
    Read V1 variant identities needed for V2 inventory discovery.
    """

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                shopify_variant_id,
                sku,
                inventory_item_id
            FROM variants
            WHERE inventory_item_id IS NOT NULL
              AND TRIM(inventory_item_id) <> ''
            ORDER BY sku, shopify_variant_id;
            """
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def main() -> int:
    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2 SHOPIFY INVENTORY DISCOVERY"
    )
    print("=" * 72)
    print(
        "MODE: READ ONLY"
    )
    print(
        "SHOPIFY MUTATIONS ALLOWED: 0"
    )
    print("-" * 72)

    mapped_variants = (
        load_mapped_inventory_items()
    )

    print(
        f"Persisted variants with InventoryItem IDs: "
        f"{len(mapped_variants)}"
    )
    print()

    client = ShopifyClient(
        store_domain=(
            SHOPIFY_STORE_DOMAIN
        ),
        client_id=(
            SHOPIFY_CLIENT_ID
        ),
        client_secret=(
            SHOPIFY_CLIENT_SECRET
        ),
        api_version=(
            SHOPIFY_API_VERSION
        ),
    )

    print(
        "Authenticating with Shopify..."
    )
    client.authenticate()
    print(
        "Authentication successful."
    )
    print()

    service = (
        ShopifyInventoryDiscoveryService(
            client
        )
    )

    report = service.discover(
        [
            row[
                "inventory_item_id"
            ]
            for row in mapped_variants
        ]
    )

    print(
        "INVENTORY PERMISSIONS"
    )
    print("-" * 72)
    print(
        f"read_inventory: "
        f"{report.has_read_inventory}"
    )
    print(
        f"write_inventory: "
        f"{report.has_write_inventory}"
    )
    print(
        "Permission ready for future live inventory sync: "
        f"{report.permission_ready_for_live_inventory}"
    )
    print()

    print(
        "ACTIVE SHOPIFY LOCATIONS"
    )
    print("-" * 72)

    for location in report.locations:
        print(
            f"{location.name}"
        )
        print(
            f"  ID: {location.location_id}"
        )
        print(
            f"  Active: {location.is_active}"
        )
        print(
            "  Fulfills online orders: "
            f"{location.fulfills_online_orders}"
        )
        print(
            "  Has active inventory: "
            f"{location.has_active_inventory}"
        )
        print()

    print(
        "MAPPED INVENTORY LEVELS"
    )
    print("-" * 72)

    for level in report.inventory_levels:
        print(
            f"SKU: {level.sku or 'NO-SKU'}"
        )
        print(
            f"  Inventory item: "
            f"{level.inventory_item_id}"
        )
        print(
            f"  Location: "
            f"{level.location_name}"
        )
        print(
            f"  Location ID: "
            f"{level.location_id}"
        )
        print(
            f"  Inventory tracked: "
            f"{level.tracked}"
        )
        print(
            f"  Level active: "
            f"{level.level_active}"
        )
        print(
            f"  Available: "
            f"{level.available_quantity}"
        )
        print()

    if report.missing_inventory_item_ids:
        print(
            "MISSING INVENTORY ITEMS"
        )
        print("-" * 72)

        for inventory_item_id in (
            report.missing_inventory_item_ids
        ):
            print(
                inventory_item_id
            )

        print()

    print(
        "DISCOVERY SUMMARY"
    )
    print("-" * 72)
    print(
        f"Locations discovered: "
        f"{len(report.locations)}"
    )
    print(
        f"Active locations: "
        f"{report.active_location_count}"
    )
    print(
        f"Inventory levels discovered: "
        f"{len(report.inventory_levels)}"
    )
    print(
        f"Missing inventory items: "
        f"{len(report.missing_inventory_item_ids)}"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )
    print(
        "SQLITE WRITES: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
