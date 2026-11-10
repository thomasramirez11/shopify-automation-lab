from __future__ import annotations

from dataclasses import dataclass


class SupplierExecutionError(RuntimeError):
    """
    Raised when a sync plan cannot be executed safely.
    """


@dataclass(frozen=True)
class InventoryMutation:
    """
    One concrete inventory mutation request.

    This is the normalized command sent to an inventory mutation adapter.
    """

    shopify_variant_id: str
    shopify_sku: str
    inventory_quantity: int

    def __post_init__(self) -> None:
        normalized_variant_id = (
            self.shopify_variant_id
            .strip()
        )

        normalized_sku = (
            self.shopify_sku
            .strip()
        )

        if not normalized_variant_id.startswith(
            "gid://shopify/ProductVariant/"
        ):
            raise SupplierExecutionError(
                "shopify_variant_id must be a Shopify ProductVariant GID."
            )

        if not normalized_sku:
            raise SupplierExecutionError(
                "shopify_sku cannot be empty."
            )

        if isinstance(
            self.inventory_quantity,
            bool,
        ) or not isinstance(
            self.inventory_quantity,
            int,
        ):
            raise SupplierExecutionError(
                "inventory_quantity must be an integer."
            )

        if self.inventory_quantity < 0:
            raise SupplierExecutionError(
                "inventory_quantity cannot be negative."
            )

        object.__setattr__(
            self,
            "shopify_variant_id",
            normalized_variant_id,
        )

        object.__setattr__(
            self,
            "shopify_sku",
            normalized_sku,
        )


@dataclass(frozen=True)
class InventoryMutationResult:
    """
    Result of one inventory mutation adapter call.
    """

    shopify_variant_id: str
    shopify_sku: str
    requested_inventory_quantity: int
    applied: bool


@dataclass(frozen=True)
class SupplierExecutionReport:
    """
    Immutable execution summary.

    In V2.5A this report is produced using the fake adapter only.
    """

    plan_fingerprint: str
    attempted_mutations: int
    applied_mutations: int
    results: tuple[
        InventoryMutationResult,
        ...,
    ]

    @property
    def succeeded(
        self,
    ) -> bool:
        return (
            self.attempted_mutations
            == self.applied_mutations
        )
