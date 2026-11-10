from __future__ import annotations

from supplier.execution.models import (
    InventoryMutation,
    InventoryMutationResult,
)


class FakeInventoryMutationAdapter:
    """
    In-memory inventory mutation adapter.

    It records requested writes but never contacts Shopify.
    """

    def __init__(
        self,
        *,
        fail_variant_ids: set[str] | None = None,
    ) -> None:
        self._mutations: list[
            InventoryMutation
        ] = []

        self._fail_variant_ids = (
            set(
                fail_variant_ids
                or set()
            )
        )

    @property
    def mutations(
        self,
    ) -> tuple[
        InventoryMutation,
        ...,
    ]:
        return tuple(
            self._mutations
        )

    def set_inventory(
        self,
        mutation: InventoryMutation,
    ) -> InventoryMutationResult:
        """
        Record the mutation request in memory.
        """

        self._mutations.append(
            mutation
        )

        applied = (
            mutation.shopify_variant_id
            not in self._fail_variant_ids
        )

        return InventoryMutationResult(
            shopify_variant_id=(
                mutation.shopify_variant_id
            ),
            shopify_sku=(
                mutation.shopify_sku
            ),
            requested_inventory_quantity=(
                mutation.inventory_quantity
            ),
            applied=applied,
        )
