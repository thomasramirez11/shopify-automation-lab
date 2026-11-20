from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum

from supplier.orchestration.models import (
    SupplierNextAction,
    SupplierSystemPosture,
)


class OperationalGateStatus(str, Enum):
    IDLE = "idle"
    APPROVAL_REQUIRED = "approval_required"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"
    PAUSED = "paused"


class OperationalGateReason(str, Enum):
    NO_WORK = "no_work"
    HUMAN_ATTENTION_PENDING = "human_attention_pending"
    RECOVERY_PENDING = "recovery_pending"
    BATCH_BLOCKED = "batch_blocked"
    BATCH_REVIEW_REQUIRED = "batch_review_required"
    MUTATION_COUNT_REVIEW_THRESHOLD = (
        "mutation_count_review_threshold"
    )
    INVENTORY_DELTA_REVIEW_THRESHOLD = (
        "inventory_delta_review_threshold"
    )
    SAFE_BATCH_REQUIRES_APPROVAL = (
        "safe_batch_requires_approval"
    )
    REPEATED_HUMAN_ATTENTION_PAUSE = (
        "repeated_human_attention_pause"
    )


@dataclass(frozen=True)
class ControlPlanePolicy:
    """
    Configurable operating rules above the batch-safety layer.

    BatchSafetyPolicy answers "is this batch intrinsically safe?"
    ControlPlanePolicy answers "is the system allowed to work on it now?"
    """

    block_new_batches_when_human_attention: bool = True
    block_new_batches_when_recovery_pending: bool = True

    manual_review_mutation_threshold: int = 3
    manual_review_total_inventory_delta_threshold: int = 60

    pause_after_consecutive_human_attention_runs: int = 3

    def __post_init__(self) -> None:
        for field_name in (
            "block_new_batches_when_human_attention",
            "block_new_batches_when_recovery_pending",
        ):
            if not isinstance(
                getattr(self, field_name),
                bool,
            ):
                raise ValueError(
                    f"{field_name} must be boolean."
                )

        for field_name in (
            "manual_review_mutation_threshold",
            "manual_review_total_inventory_delta_threshold",
            "pause_after_consecutive_human_attention_runs",
        ):
            value = getattr(
                self,
                field_name,
            )

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
            ):
                raise ValueError(
                    f"{field_name} must be an integer greater than zero."
                )

    @property
    def fingerprint(self) -> str:
        payload = {
            "block_new_batches_when_human_attention":
                self.block_new_batches_when_human_attention,
            "block_new_batches_when_recovery_pending":
                self.block_new_batches_when_recovery_pending,
            "manual_review_mutation_threshold":
                self.manual_review_mutation_threshold,
            "manual_review_total_inventory_delta_threshold":
                self.manual_review_total_inventory_delta_threshold,
            "pause_after_consecutive_human_attention_runs":
                self.pause_after_consecutive_human_attention_runs,
        }

        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            canonical.encode(
                "utf-8"
            )
        ).hexdigest()


@dataclass(frozen=True)
class ControlPlanePolicyDecision:
    posture: SupplierSystemPosture
    next_action: SupplierNextAction

    gate_status: OperationalGateStatus
    reasons: tuple[
        OperationalGateReason,
        ...,
    ]

    policy_fingerprint: str
    consecutive_human_attention_runs: int
