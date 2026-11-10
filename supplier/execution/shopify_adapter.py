from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, Protocol

from database.connection import get_db_connection
from supplier.execution.models import (
    InventoryMutation,
    InventoryMutationResult,
    SupplierExecutionError,
)


INVENTORY_SET_QUANTITIES_MUTATION = """
mutation InventorySetQuantities(
    $input: InventorySetQuantitiesInput!,
    $idempotencyKey: String!
) {
    inventorySetQuantities(
        input: $input
    ) @idempotent(key: $idempotencyKey) {
        inventoryAdjustmentGroup {
            reason
            referenceDocumentUri
            changes {
                name
                delta
                quantityAfterChange
            }
        }
        userErrors {
            code
            field
            message
        }
    }
}
"""


class LiveShopifyWriteDisabledError(SupplierExecutionError):
    """Raised when a Shopify mutation is attempted while the kill switch is off."""


class ShopifyInventoryTargetError(SupplierExecutionError):
    """Raised when an inventory item or location cannot be resolved safely."""


@dataclass(frozen=True)
class ShopifyInventoryTarget:
    """Concrete target required by Shopify inventorySetQuantities."""

    inventory_item_id: str
    location_id: str

    def __post_init__(self) -> None:
        inventory_item_id = self.inventory_item_id.strip()
        location_id = self.location_id.strip()

        if not inventory_item_id.startswith("gid://shopify/InventoryItem/"):
            raise ShopifyInventoryTargetError(
                "inventory_item_id must be a Shopify InventoryItem GID."
            )

        if not location_id.startswith("gid://shopify/Location/"):
            raise ShopifyInventoryTargetError(
                "location_id must be a Shopify Location GID."
            )

        object.__setattr__(self, "inventory_item_id", inventory_item_id)
        object.__setattr__(self, "location_id", location_id)


class InventoryTargetResolver(Protocol):
    def resolve(
        self,
        shopify_variant_id: str,
    ) -> ShopifyInventoryTarget | None:
        ...


class SQLiteInventoryTargetResolver:
    """
    Resolve InventoryItem from V1 SQLite plus an explicit Shopify location.

    We deliberately never guess a location.
    """

    def __init__(
        self,
        *,
        location_id: str,
        connection_factory: Callable = get_db_connection,
    ) -> None:
        normalized_location_id = location_id.strip()

        if not normalized_location_id.startswith("gid://shopify/Location/"):
            raise ShopifyInventoryTargetError(
                "location_id must be a Shopify Location GID."
            )

        self._location_id = normalized_location_id
        self._connection_factory = connection_factory

    def resolve(
        self,
        shopify_variant_id: str,
    ) -> ShopifyInventoryTarget | None:
        normalized_variant_id = shopify_variant_id.strip()

        with self._connection_factory() as connection:
            row = connection.execute(
                """
                SELECT inventory_item_id
                FROM variants
                WHERE shopify_variant_id = ?;
                """,
                (normalized_variant_id,),
            ).fetchone()

        if row is None:
            return None

        row_data = dict(row)
        inventory_item_id = row_data.get("inventory_item_id")

        if not isinstance(inventory_item_id, str) or not inventory_item_id.strip():
            raise ShopifyInventoryTargetError(
                "Persisted mapped variant has no inventory_item_id."
            )

        return ShopifyInventoryTarget(
            inventory_item_id=inventory_item_id,
            location_id=self._location_id,
        )


class ShopifyInventoryMutationAdapter:
    """
    Real Shopify GraphQL inventory mutation adapter.

    LIVE WRITES ARE DISABLED BY DEFAULT.
    """

    def __init__(
        self,
        *,
        shopify_client,
        target_resolver: InventoryTargetResolver,
        live_writes_enabled: bool = False,
    ) -> None:
        self._shopify_client = shopify_client
        self._target_resolver = target_resolver
        self._live_writes_enabled = live_writes_enabled

    def set_inventory(
        self,
        mutation: InventoryMutation,
    ) -> InventoryMutationResult:
        """
        Set 'available' inventory using absolute quantity + CAS.
        """

        if not self._live_writes_enabled:
            raise LiveShopifyWriteDisabledError(
                "Live Shopify inventory writes are disabled."
            )

        if mutation.expected_current_quantity is None:
            raise SupplierExecutionError(
                "Live Shopify inventory mutation requires "
                "expected_current_quantity for compare-and-swap."
            )

        target = self._target_resolver.resolve(
            mutation.shopify_variant_id
        )

        if target is None:
            raise ShopifyInventoryTargetError(
                "Could not resolve Shopify inventory target for "
                f"{mutation.shopify_variant_id}."
            )

        variables = build_inventory_set_variables(
            mutation=mutation,
            target=target,
        )

        data = self._shopify_client.graphql(
            INVENTORY_SET_QUANTITIES_MUTATION,
            variables,
        )

        payload = (
            data.get("inventorySetQuantities")
            if isinstance(data, dict)
            else None
        )

        if not isinstance(payload, dict):
            raise SupplierExecutionError(
                "Shopify inventory mutation returned an invalid payload."
            )

        user_errors = payload.get("userErrors") or []

        if user_errors:
            details = "; ".join(
                _format_user_error(error)
                for error in user_errors
            )

            raise SupplierExecutionError(
                "Shopify rejected inventory mutation: "
                f"{details}"
            )

        return InventoryMutationResult(
            shopify_variant_id=mutation.shopify_variant_id,
            shopify_sku=mutation.shopify_sku,
            requested_inventory_quantity=mutation.inventory_quantity,
            applied=True,
        )


def build_inventory_set_variables(
    *,
    mutation: InventoryMutation,
    target: ShopifyInventoryTarget,
) -> dict:
    """
    Build Shopify inventorySetQuantities variables without doing I/O.
    """

    if mutation.expected_current_quantity is None:
        raise SupplierExecutionError(
            "expected_current_quantity is required for Shopify CAS."
        )

    idempotency_key = build_inventory_idempotency_key(
        mutation=mutation,
        target=target,
    )

    return {
        "input": {
            "name": "available",
            "reason": "correction",
            "referenceDocumentUri": (
                "shopify-automation-lab://"
                f"supplier-sync/{idempotency_key}"
            ),
            "quantities": [
                {
                    "inventoryItemId": target.inventory_item_id,
                    "locationId": target.location_id,
                    "quantity": mutation.inventory_quantity,
                    "changeFromQuantity": mutation.expected_current_quantity,
                }
            ],
        },
        "idempotencyKey": idempotency_key,
    }


def build_inventory_idempotency_key(
    *,
    mutation: InventoryMutation,
    target: ShopifyInventoryTarget,
) -> str:
    """
    Stable UUID for the same logical inventory mutation.
    """

    identity = "|".join(
        (
            mutation.shopify_variant_id,
            target.inventory_item_id,
            target.location_id,
            str(mutation.expected_current_quantity),
            str(mutation.inventory_quantity),
        )
    )

    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            identity,
        )
    )


def _format_user_error(error) -> str:
    if not isinstance(error, dict):
        return str(error)

    code = error.get("code") or "UNKNOWN"
    message = error.get("message") or "Unknown Shopify error"

    return f"{code}: {message}"
