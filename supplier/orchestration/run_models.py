from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OrchestrationTransitionType(str, Enum):
    INITIAL = 'initial'
    UNCHANGED = 'unchanged'
    POSTURE_CHANGED = 'posture_changed'
    ACTION_CHANGED = 'action_changed'
    POSTURE_AND_ACTION_CHANGED = 'posture_and_action_changed'


@dataclass(frozen=True)
class StoredOrchestrationRun:
    run_id: int
    supplier_code: str
    orchestration_fingerprint: str
    manifest_fingerprint: str
    posture: str
    next_action: str
    planned_mutations: int
    review_items: int
    blocked_items: int
    no_action_items: int
    queued_retry_attempts: int
    dead_letter_awaiting_human: int
    dead_letter_acknowledged: int
    resolution_recorded: int
    reentry_authorized: int
    reentry_started: int
    reentry_failed: int
    resolution_closed: int
    previous_run_id: int | None
    previous_posture: str | None
    posture_changed: int
    next_action_changed: int
    created_at: str


@dataclass(frozen=True)
class OrchestrationRunResult:
    run: StoredOrchestrationRun
    transition_type: OrchestrationTransitionType

    @property
    def changed(self) -> bool:
        return self.transition_type != OrchestrationTransitionType.UNCHANGED
