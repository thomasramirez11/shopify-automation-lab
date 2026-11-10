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


from supplier.execution.models import InventoryMutation  # noqa: E402
from supplier.execution.shopify_adapter import (  # noqa: E402
    LiveShopifyWriteDisabledError,
    ShopifyInventoryMutationAdapter,
    ShopifyInventoryTarget,
    build_inventory_set_variables,
)
from supplier.execution.safety import (  # noqa: E402
    LIVE_WRITE_ENV_VAR,
    live_writes_enabled_from_environment,
)


class NoCallShopifyClient:
    def __init__(self) -> None:
        self.calls = 0

    def graphql(self, query, variables):
        self.calls += 1
        raise RuntimeError(
            "GraphQL should not be called while live writes are disabled."
        )


class PreviewTargetResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, shopify_variant_id):
        self.calls += 1
        return ShopifyInventoryTarget(
            inventory_item_id="gid://shopify/InventoryItem/123",
            location_id="gid://shopify/Location/456",
        )


def main() -> int:
    enabled = live_writes_enabled_from_environment()

    mutation = InventoryMutation(
        shopify_variant_id="gid://shopify/ProductVariant/111",
        shopify_sku="PREVIEW-SKU",
        inventory_quantity=25,
        expected_current_quantity=1,
    )

    target = ShopifyInventoryTarget(
        inventory_item_id="gid://shopify/InventoryItem/123",
        location_id="gid://shopify/Location/456",
    )

    variables = build_inventory_set_variables(
        mutation=mutation,
        target=target,
    )

    client = NoCallShopifyClient()
    resolver = PreviewTargetResolver()

    adapter = ShopifyInventoryMutationAdapter(
        shopify_client=client,
        target_resolver=resolver,
        live_writes_enabled=enabled,
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2 LIVE WRITE GATE PREVIEW"
    )
    print("=" * 68)
    print(
        f"{LIVE_WRITE_ENV_VAR}: {enabled}"
    )
    print(
        "Prepared quantity: "
        f"{mutation.inventory_quantity}"
    )
    print(
        "Expected current quantity (CAS): "
        f"{mutation.expected_current_quantity}"
    )
    print(
        "Prepared location: "
        f"{target.location_id}"
    )
    print(
        "Prepared inventory item: "
        f"{target.inventory_item_id}"
    )
    print(
        "Idempotency key: "
        f"{variables['idempotencyKey']}"
    )
    print("-" * 68)

    if enabled:
        print(
            "PREVIEW ABORTED: live writes are enabled in the environment."
        )
        return 1

    try:
        adapter.set_inventory(mutation)

    except LiveShopifyWriteDisabledError as exc:
        print("Write gate result: BLOCKED")
        print(f"Reason: {exc}")

    print(
        f"Target resolver calls: {resolver.calls}"
    )
    print(
        f"Shopify GraphQL calls: {client.calls}"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
