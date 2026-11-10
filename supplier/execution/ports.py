from __future__ import annotations

from typing import Protocol

from supplier.execution.models import (
    InventoryMutation,
    InventoryMutationResult,
)


class InventoryMutationPort(Protocol):
    """
    Application-facing contract for changing Shopify inventory.

    Real Shopify API code will implement this later. V2.5A uses only a fake
    in-memory adapter.
    """

    def set_inventory(
        self,
        mutation: InventoryMutation,
    ) -> InventoryMutationResult:
        """
        Apply one inventory quantity mutation.
        """
