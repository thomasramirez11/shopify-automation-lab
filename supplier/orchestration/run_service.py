from __future__ import annotations

from supplier.orchestration.run_models import OrchestrationRunResult, OrchestrationTransitionType
from supplier.orchestration.run_repository import SupplierOrchestrationRunRepository


class SupplierOrchestrationRunService:
    """Record one orchestrator snapshot and classify its state transition."""

    def __init__(self, repository: SupplierOrchestrationRunRepository) -> None:
        self._repository = repository

    def record_snapshot(self, snapshot) -> OrchestrationRunResult:
        previous = self._repository.get_latest(snapshot.supplier_code)
        run = self._repository.append(snapshot=snapshot, previous_run=previous)
        return OrchestrationRunResult(
            run=run,
            transition_type=classify_transition(previous_run=previous, current_run=run),
        )


def classify_transition(*, previous_run, current_run) -> OrchestrationTransitionType:
    if previous_run is None:
        return OrchestrationTransitionType.INITIAL
    posture_changed = previous_run.posture != current_run.posture
    action_changed = previous_run.next_action != current_run.next_action
    if posture_changed and action_changed:
        return OrchestrationTransitionType.POSTURE_AND_ACTION_CHANGED
    if posture_changed:
        return OrchestrationTransitionType.POSTURE_CHANGED
    if action_changed:
        return OrchestrationTransitionType.ACTION_CHANGED
    return OrchestrationTransitionType.UNCHANGED
