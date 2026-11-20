from __future__ import annotations

from supplier.batch.models import BatchSafetyStatus
from supplier.orchestration.models import (
    SupplierNextAction,
    SupplierSystemPosture,
)
from supplier.orchestration.policy_models import (
    ControlPlanePolicy,
    ControlPlanePolicyDecision,
    OperationalGateReason,
    OperationalGateStatus,
)


DEFAULT_CONTROL_PLANE_POLICY = (
    ControlPlanePolicy()
)


def evaluate_control_plane_policy(
    *,
    manifest,
    backlog,
    policy: ControlPlanePolicy = (
        DEFAULT_CONTROL_PLANE_POLICY
    ),
    consecutive_human_attention_runs: int = 0,
) -> ControlPlanePolicyDecision:
    if (
        isinstance(
            consecutive_human_attention_runs,
            bool,
        )
        or not isinstance(
            consecutive_human_attention_runs,
            int,
        )
        or consecutive_human_attention_runs < 0
    ):
        raise ValueError(
            "consecutive_human_attention_runs must be a non-negative integer."
        )

    if (
        backlog.unresolved_human_cases > 0
        and policy.block_new_batches_when_human_attention
    ):
        if (
            consecutive_human_attention_runs
            >= policy
            .pause_after_consecutive_human_attention_runs
        ):
            return _decision(
                policy=policy,
                posture=(
                    SupplierSystemPosture
                    .HUMAN_ATTENTION
                ),
                next_action=(
                    SupplierNextAction
                    .REVIEW_DEAD_LETTER_CASES
                ),
                gate_status=(
                    OperationalGateStatus.PAUSED
                ),
                reasons=(
                    OperationalGateReason
                    .HUMAN_ATTENTION_PENDING,
                    OperationalGateReason
                    .REPEATED_HUMAN_ATTENTION_PAUSE,
                ),
                consecutive=(
                    consecutive_human_attention_runs
                ),
            )

        return _decision(
            policy=policy,
            posture=(
                SupplierSystemPosture
                .HUMAN_ATTENTION
            ),
            next_action=(
                SupplierNextAction
                .REVIEW_DEAD_LETTER_CASES
            ),
            gate_status=(
                OperationalGateStatus.BLOCKED
            ),
            reasons=(
                OperationalGateReason
                .HUMAN_ATTENTION_PENDING,
            ),
            consecutive=(
                consecutive_human_attention_runs
            ),
        )

    if (
        backlog.queued_retry_attempts > 0
        and policy.block_new_batches_when_recovery_pending
    ):
        return _decision(
            policy=policy,
            posture=(
                SupplierSystemPosture
                .RECOVERY_PENDING
            ),
            next_action=(
                SupplierNextAction
                .PROCESS_RETRY_QUEUE
            ),
            gate_status=(
                OperationalGateStatus.BLOCKED
            ),
            reasons=(
                OperationalGateReason
                .RECOVERY_PENDING,
            ),
            consecutive=(
                consecutive_human_attention_runs
            ),
        )

    if (
        manifest.status
        == BatchSafetyStatus.BLOCKED
    ):
        return _decision(
            policy=policy,
            posture=(
                SupplierSystemPosture.BLOCKED
            ),
            next_action=(
                SupplierNextAction
                .FIX_BLOCKING_ISSUES
            ),
            gate_status=(
                OperationalGateStatus.BLOCKED
            ),
            reasons=(
                OperationalGateReason
                .BATCH_BLOCKED,
            ),
            consecutive=(
                consecutive_human_attention_runs
            ),
        )

    if (
        manifest.status
        == BatchSafetyStatus.REVIEW_REQUIRED
    ):
        return _decision(
            policy=policy,
            posture=(
                SupplierSystemPosture
                .REVIEW_REQUIRED
            ),
            next_action=(
                SupplierNextAction
                .REVIEW_BATCH
            ),
            gate_status=(
                OperationalGateStatus
                .REVIEW_REQUIRED
            ),
            reasons=(
                OperationalGateReason
                .BATCH_REVIEW_REQUIRED,
            ),
            consecutive=(
                consecutive_human_attention_runs
            ),
        )

    if (
        manifest.status
        == BatchSafetyStatus.READY
    ):
        review_reasons = []

        if (
            manifest.planned_mutations
            > policy
            .manual_review_mutation_threshold
        ):
            review_reasons.append(
                OperationalGateReason
                .MUTATION_COUNT_REVIEW_THRESHOLD
            )

        if (
            manifest.total_absolute_inventory_delta
            > policy
            .manual_review_total_inventory_delta_threshold
        ):
            review_reasons.append(
                OperationalGateReason
                .INVENTORY_DELTA_REVIEW_THRESHOLD
            )

        if review_reasons:
            return _decision(
                policy=policy,
                posture=(
                    SupplierSystemPosture
                    .REVIEW_REQUIRED
                ),
                next_action=(
                    SupplierNextAction
                    .REVIEW_BATCH
                ),
                gate_status=(
                    OperationalGateStatus
                    .REVIEW_REQUIRED
                ),
                reasons=tuple(
                    review_reasons
                ),
                consecutive=(
                    consecutive_human_attention_runs
                ),
            )

        return _decision(
            policy=policy,
            posture=(
                SupplierSystemPosture
                .READY_FOR_APPROVAL
            ),
            next_action=(
                SupplierNextAction
                .APPROVE_BATCH
            ),
            gate_status=(
                OperationalGateStatus
                .APPROVAL_REQUIRED
            ),
            reasons=(
                OperationalGateReason
                .SAFE_BATCH_REQUIRES_APPROVAL,
            ),
            consecutive=(
                consecutive_human_attention_runs
            ),
        )

    return _decision(
        policy=policy,
        posture=(
            SupplierSystemPosture.IDLE
        ),
        next_action=(
            SupplierNextAction.NONE
        ),
        gate_status=(
            OperationalGateStatus.IDLE
        ),
        reasons=(
            OperationalGateReason.NO_WORK,
        ),
        consecutive=(
            consecutive_human_attention_runs
        ),
    )


def _decision(
    *,
    policy,
    posture,
    next_action,
    gate_status,
    reasons,
    consecutive,
):
    return ControlPlanePolicyDecision(
        posture=posture,
        next_action=next_action,
        gate_status=gate_status,
        reasons=reasons,
        policy_fingerprint=(
            policy.fingerprint
        ),
        consecutive_human_attention_runs=(
            consecutive
        ),
    )
