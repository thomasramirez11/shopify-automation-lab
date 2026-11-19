from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from supplier.batch.models import BatchSafetyManifest
from supplier.decision.models import SupplierSyncDecision
from supplier.plan.models import SupplierSyncPlan


class SupplierSystemPosture(str, Enum):
    IDLE = "idle"
    READY_FOR_APPROVAL = "ready_for_approval"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"
    RECOVERY_PENDING = "recovery_pending"
    HUMAN_ATTENTION = "human_attention"


class SupplierNextAction(str, Enum):
    NONE = "none"
    APPROVE_BATCH = "approve_batch"
    REVIEW_BATCH = "review_batch"
    FIX_BLOCKING_ISSUES = "fix_blocking_issues"
    PROCESS_RETRY_QUEUE = "process_retry_queue"
    REVIEW_DEAD_LETTER_CASES = "review_dead_letter_cases"


@dataclass(frozen=True)
class SupplierOperationsBacklog:
    queued_retry_attempts: int = 0

    dead_letter_awaiting_human: int = 0
    dead_letter_acknowledged: int = 0

    resolution_recorded: int = 0
    reentry_authorized: int = 0
    reentry_started: int = 0
    reentry_failed: int = 0
    resolution_closed: int = 0

    def __post_init__(self) -> None:
        for field_name, value in self.__dict__.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(
                    f"{field_name} must be a non-negative integer."
                )

    @property
    def unresolved_human_cases(self) -> int:
        return (
            self.dead_letter_awaiting_human
            + self.dead_letter_acknowledged
            + self.resolution_recorded
            + self.reentry_authorized
            + self.reentry_started
            + self.reentry_failed
        )


@dataclass(frozen=True)
class SupplierOperationsSnapshot:
    supplier_code: str

    active_mapping_count: int
    supplier_product_count: int

    decisions: tuple[SupplierSyncDecision, ...]
    plan: SupplierSyncPlan
    manifest: BatchSafetyManifest

    backlog: SupplierOperationsBacklog

    posture: SupplierSystemPosture
    next_action: SupplierNextAction

    orchestration_fingerprint: str

    @property
    def decision_count(self) -> int:
        return len(self.decisions)
