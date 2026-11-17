from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BatchSafetyError(ValueError):
    """Raised when batch safety configuration is invalid."""


class BatchSafetyStatus(str, Enum):
    EMPTY = "empty"
    READY = "ready"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class BatchSafetyReason(str, Enum):
    NO_MUTATIONS = "no_mutations"
    WITHIN_BUDGET = "within_budget"
    PLAN_HAS_REVIEW_ITEMS = "plan_has_review_items"
    PLAN_HAS_BLOCKED_ITEMS = "plan_has_blocked_items"
    TOO_MANY_MUTATIONS = "too_many_mutations"
    TOTAL_INVENTORY_DELTA_EXCEEDED = (
        "total_inventory_delta_exceeded"
    )
    SINGLE_ITEM_DELTA_EXCEEDED = (
        "single_item_delta_exceeded"
    )


@dataclass(frozen=True)
class BatchSafetyPolicy:
    """
    Limits the blast radius of one future automated supplier batch.

    max_mutations_per_batch:
        Maximum number of Shopify inventory changes allowed in one batch.

    max_total_absolute_inventory_delta:
        Maximum sum of absolute inventory movement in one batch.

    max_single_item_absolute_delta:
        Extra batch-level ceiling for any one item.
    """

    max_mutations_per_batch: int = 5
    max_total_absolute_inventory_delta: int = 100
    max_single_item_absolute_delta: int = 50

    def __post_init__(self) -> None:
        _require_non_negative_integer(
            "max_mutations_per_batch",
            self.max_mutations_per_batch,
        )
        _require_non_negative_integer(
            "max_total_absolute_inventory_delta",
            self.max_total_absolute_inventory_delta,
        )
        _require_non_negative_integer(
            "max_single_item_absolute_delta",
            self.max_single_item_absolute_delta,
        )

        if self.max_mutations_per_batch == 0:
            raise BatchSafetyError(
                "max_mutations_per_batch must be greater than zero."
            )


@dataclass(frozen=True)
class BatchMutationPreview:
    supplier_sku: str
    shopify_variant_id: str
    shopify_sku: str
    current_inventory_quantity: int
    proposed_inventory_quantity: int
    inventory_delta: int

    @property
    def absolute_inventory_delta(
        self,
    ) -> int:
        return abs(
            self.inventory_delta
        )


@dataclass(frozen=True)
class BatchSafetyManifest:
    source_plan_fingerprint: str
    manifest_fingerprint: str

    status: BatchSafetyStatus
    reasons: tuple[BatchSafetyReason, ...]

    mutations: tuple[BatchMutationPreview, ...]

    planned_mutations: int
    review_items: int
    blocked_items: int
    no_action_items: int

    total_absolute_inventory_delta: int
    largest_single_item_absolute_delta: int

    policy: BatchSafetyPolicy

    @property
    def is_ready(
        self,
    ) -> bool:
        return (
            self.status
            == BatchSafetyStatus.READY
        )

    @property
    def is_empty(
        self,
    ) -> bool:
        return (
            self.status
            == BatchSafetyStatus.EMPTY
        )


def _require_non_negative_integer(
    field_name: str,
    value,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
    ):
        raise BatchSafetyError(
            f"{field_name} must be an integer."
        )

    if value < 0:
        raise BatchSafetyError(
            f"{field_name} cannot be negative."
        )
