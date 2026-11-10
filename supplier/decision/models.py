from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SupplierSyncPolicyError(ValueError):
    """
    Raised when a synchronization policy or decision input is invalid.
    """


class SyncDecisionStatus(str, Enum):
    """
    Safety-oriented decision outcomes.

    None of these statuses perform a write by themselves.
    """

    NO_ACTION = "no_action"
    ELIGIBLE = "eligible"
    REVIEW = "review"
    BLOCKED = "blocked"


class SyncDecisionReason(str, Enum):
    """
    Machine-readable explanation for one decision.
    """

    ALREADY_MATCHED = "already_matched"
    INVENTORY_MISMATCH_WITHIN_LIMIT = (
        "inventory_mismatch_within_limit"
    )
    INVENTORY_CHANGE_EXCEEDS_LIMIT = (
        "inventory_change_exceeds_limit"
    )
    COST_CHANGE_REQUIRES_REVIEW = (
        "cost_change_requires_review"
    )
    STOCK_AND_COST_CHANGE_REQUIRES_REVIEW = (
        "stock_and_cost_change_requires_review"
    )
    SUPPLIER_PRODUCT_MISSING = (
        "supplier_product_missing"
    )
    SHOPIFY_VARIANT_MISSING = (
        "shopify_variant_missing"
    )


@dataclass(frozen=True)
class InventorySyncPolicy:
    """
    V2 inventory safety policy.

    max_inventory_delta is the largest absolute inventory adjustment that
    may be marked ELIGIBLE without human review.

    Example:
        Shopify stock = 2
        Supplier stock = 40
        Delta = +38

        If max_inventory_delta = 50:
            ELIGIBLE

        If max_inventory_delta = 20:
            REVIEW
    """

    max_inventory_delta: int = 50

    def __post_init__(self) -> None:
        if isinstance(
            self.max_inventory_delta,
            bool,
        ) or not isinstance(
            self.max_inventory_delta,
            int,
        ):
            raise SupplierSyncPolicyError(
                "max_inventory_delta must be an integer."
            )

        if self.max_inventory_delta < 0:
            raise SupplierSyncPolicyError(
                "max_inventory_delta cannot be negative."
            )


@dataclass(frozen=True)
class SupplierSyncDecision:
    """
    Immutable output from the V2 decision policy.

    proposed_inventory_quantity is populated only when inventory synchronization
    is safe enough to be considered ELIGIBLE. It is still only a proposal.
    """

    supplier_code: str
    supplier_sku: str
    shopify_variant_id: str
    shopify_sku: str

    status: SyncDecisionStatus
    reason: SyncDecisionReason

    current_inventory_quantity: int | None
    supplier_inventory_quantity: int | None
    inventory_delta: int | None
    proposed_inventory_quantity: int | None

    @property
    def requires_human_review(
        self,
    ) -> bool:
        return (
            self.status
            == SyncDecisionStatus.REVIEW
        )

    @property
    def is_blocked(
        self,
    ) -> bool:
        return (
            self.status
            == SyncDecisionStatus.BLOCKED
        )

    @property
    def is_eligible(
        self,
    ) -> bool:
        return (
            self.status
            == SyncDecisionStatus.ELIGIBLE
        )
