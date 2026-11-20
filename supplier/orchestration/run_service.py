from __future__ import annotations

from supplier.orchestration.run_models import (
    ConfigurationTransitionType,
    OrchestrationRunResult,
    OrchestrationTransitionType,
)
from supplier.orchestration.run_repository import SupplierOrchestrationRunRepository


class SupplierOrchestrationRunService:
    def __init__(self, repository: SupplierOrchestrationRunRepository) -> None:
        self._repository = repository

    def record_snapshot(self, snapshot) -> OrchestrationRunResult:
        previous = self._repository.get_latest(snapshot.supplier_code)
        run = self._repository.append(snapshot=snapshot, previous_run=previous)
        return OrchestrationRunResult(
            run=run,
            transition_type=classify_transition(previous_run=previous, current_run=run),
            configuration_transition_type=classify_configuration_transition(
                previous_run=previous,
                current_run=run,
            ),
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


def classify_configuration_transition(*, previous_run, current_run) -> ConfigurationTransitionType:
    if previous_run is None:
        return ConfigurationTransitionType.INITIAL
    policy_changed = bool(current_run.policy_changed)
    manifest_changed = bool(current_run.manifest_changed)
    if (
        policy_changed
        and not manifest_changed
        and not previous_run.policy_fingerprint
        and current_run.policy_fingerprint
    ):
        return ConfigurationTransitionType.POLICY_PROVENANCE_ESTABLISHED
    if policy_changed and manifest_changed:
        return ConfigurationTransitionType.POLICY_AND_MANIFEST_CHANGED
    if policy_changed:
        return ConfigurationTransitionType.POLICY_CHANGED
    if manifest_changed:
        return ConfigurationTransitionType.MANIFEST_CHANGED
    return ConfigurationTransitionType.UNCHANGED
