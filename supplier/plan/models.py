from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from supplier.decision.models import (
    SyncDecisionReason,
    SyncDecisionStatus,
)


class SupplierSyncPlanError(ValueError):
    """
    Raised when a dry-run synchronization plan is internally inconsistent.
    """


class SyncPlanMode(str, Enum):
    """
    V2 planning modes.

    V2.4B intentionally supports DRY_RUN only.
    """

    DRY_RUN = "dry_run"


class SyncPlanAction(str, Enum):
    """
    Planned operation type.

    NONE means the item is visible in the plan but will not mutate Shopify.
    """

    NONE = "none"
    SET_INVENTORY = "set_inventory"


@dataclass(frozen=True)
class SupplierSyncPlanItem:
    """
    Immutable representation of one decision inside a dry-run plan.
    """

    supplier_code: str
    supplier_sku: str
    shopify_variant_id: str
    shopify_sku: str

    decision_status: SyncDecisionStatus
    decision_reason: SyncDecisionReason

    action: SyncPlanAction

    current_inventory_quantity: int | None
    proposed_inventory_quantity: int | None
    inventory_delta: int | None

    @property
    def would_mutate_shopify(
        self,
    ) -> bool:
        return (
            self.action
            == SyncPlanAction.SET_INVENTORY
        )


@dataclass(frozen=True)
class SupplierSyncPlan:
    """
    Complete V2 dry-run plan.

    fingerprint is a deterministic SHA-256 digest of the plan contents.
    It will later help us detect stale or changed plans before execution.
    """

    mode: SyncPlanMode
    items: tuple[SupplierSyncPlanItem, ...]
    fingerprint: str

    @property
    def planned_mutations(
        self,
    ) -> int:
        return sum(
            1
            for item in self.items
            if item.would_mutate_shopify
        )

    @property
    def review_items(
        self,
    ) -> int:
        return sum(
            1
            for item in self.items
            if (
                item.decision_status
                == SyncDecisionStatus.REVIEW
            )
        )

    @property
    def blocked_items(
        self,
    ) -> int:
        return sum(
            1
            for item in self.items
            if (
                item.decision_status
                == SyncDecisionStatus.BLOCKED
            )
        )

    @property
    def no_action_items(
        self,
    ) -> int:
        return sum(
            1
            for item in self.items
            if (
                item.decision_status
                == SyncDecisionStatus.NO_ACTION
            )
        )
