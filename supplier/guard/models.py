from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionGuardStatus(str, Enum):
    """
    Result of the final read-only gate before a future executor.
    """

    READY = "ready"
    APPROVAL_REQUIRED = "approval_required"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    REVIEW_REQUIRED = "review_required"
    BLOCKED_ITEMS_PRESENT = "blocked_items_present"
    NO_MUTATIONS = "no_mutations"


@dataclass(frozen=True)
class ExecutionGuardReport:
    """
    Immutable authorization result.

    READY still does not perform any Shopify mutation. It only means the
    current plan is unchanged, explicitly approved, and contains no policy
    blockers/review items.
    """

    status: ExecutionGuardStatus
    current_plan_fingerprint: str
    approved_plan_fingerprint: str | None
    planned_mutations: int
    review_items: int
    blocked_items: int

    @property
    def can_execute(
        self,
    ) -> bool:
        return (
            self.status
            == ExecutionGuardStatus.READY
        )
