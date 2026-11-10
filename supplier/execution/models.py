from __future__ import annotations

from dataclasses import dataclass


class SupplierExecutionError(RuntimeError):
    """Raised when a sync plan cannot be executed safely."""


@dataclass(frozen=True)
class InventoryMutation:
    """
    One concrete inventory mutation request.

    expected_current_quantity carries the quantity observed when the plan was
    built so a real Shopify adapter can use compare-and-swap protection.
    """

    shopify_variant_id: str
    shopify_sku: str
    inventory_quantity: int
    expected_current_quantity: int | None = None

    def __post_init__(self) -> None:
        variant_id = self.shopify_variant_id.strip()
        sku = self.shopify_sku.strip()

        if not variant_id.startswith("gid://shopify/ProductVariant/"):
            raise SupplierExecutionError(
                "shopify_variant_id must be a Shopify ProductVariant GID."
            )

        if not sku:
            raise SupplierExecutionError(
                "shopify_sku cannot be empty."
            )

        if isinstance(self.inventory_quantity, bool) or not isinstance(
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

        if (
            self.expected_current_quantity is not None
            and (
                isinstance(self.expected_current_quantity, bool)
                or not isinstance(self.expected_current_quantity, int)
            )
        ):
            raise SupplierExecutionError(
                "expected_current_quantity must be an integer when provided."
            )

        if (
            self.expected_current_quantity is not None
            and self.expected_current_quantity < 0
        ):
            raise SupplierExecutionError(
                "expected_current_quantity cannot be negative."
            )

        object.__setattr__(self, "shopify_variant_id", variant_id)
        object.__setattr__(self, "shopify_sku", sku)


@dataclass(frozen=True)
class InventoryMutationResult:
    """Result of one inventory mutation adapter call."""

    shopify_variant_id: str
    shopify_sku: str
    requested_inventory_quantity: int
    applied: bool


@dataclass(frozen=True)
class SupplierExecutionReport:
    """Immutable execution summary."""

    plan_fingerprint: str
    attempted_mutations: int
    applied_mutations: int
    results: tuple[InventoryMutationResult, ...]

    @property
    def succeeded(self) -> bool:
        return self.attempted_mutations == self.applied_mutations
