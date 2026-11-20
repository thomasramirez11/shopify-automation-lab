from __future__ import annotations

from supplier.orchestration.health_models import (
    ControlPlaneHealthReport,
    ControlPlaneHealthStatus,
    ControlPlaneSLOPolicy,
    HealthReason,
    SLOCheck,
)


HEALTHY_POSTURES = {
    "idle",
    "ready_for_approval",
}

DEGRADED_POSTURES = {
    "review_required",
    "recovery_pending",
}

CRITICAL_POSTURES = {
    "blocked",
    "human_attention",
}


def evaluate_control_plane_health(
    *,
    snapshot,
    recent_runs,
    policy: ControlPlaneSLOPolicy,
) -> ControlPlaneHealthReport:
    """
    Derive an explainable 0-100 health score plus SLO compliance.

    Score weights:
    - current posture: 35
    - current backlog: 25
    - recent healthy-run ratio: 25
    - consecutive healthy-run streak: 15
    """

    runs = tuple(
        recent_runs[
            : policy.history_window_runs
        ]
    )

    healthy_runs = sum(
        1
        for run in runs
        if run.posture in HEALTHY_POSTURES
    )

    healthy_percentage = (
        round(
            (
                healthy_runs
                / len(runs)
            )
            * 100.0,
            1,
        )
        if runs
        else 0.0
    )

    healthy_streak = (
        _consecutive_healthy_runs(
            runs
        )
    )

    unresolved_human_cases = (
        snapshot.backlog
        .unresolved_human_cases
    )

    queued_retries = (
        snapshot.backlog
        .queued_retry_attempts
    )

    checks = (
        SLOCheck(
            name="history_depth",
            met=(
                len(runs)
                >= policy.minimum_history_runs
            ),
            observed=str(
                len(runs)
            ),
            target=(
                f">={policy.minimum_history_runs}"
            ),
        ),
        SLOCheck(
            name="healthy_run_percentage",
            met=(
                healthy_percentage
                >= policy.minimum_healthy_run_percentage
            ),
            observed=(
                f"{healthy_percentage:.1f}%"
            ),
            target=(
                f">={float(policy.minimum_healthy_run_percentage):.1f}%"
            ),
        ),
        SLOCheck(
            name="consecutive_healthy_runs",
            met=(
                healthy_streak
                >= policy.minimum_consecutive_healthy_runs
            ),
            observed=str(
                healthy_streak
            ),
            target=(
                f">={policy.minimum_consecutive_healthy_runs}"
            ),
        ),
        SLOCheck(
            name="unresolved_human_cases",
            met=(
                unresolved_human_cases
                <= policy.maximum_unresolved_human_cases
            ),
            observed=str(
                unresolved_human_cases
            ),
            target=(
                f"<={policy.maximum_unresolved_human_cases}"
            ),
        ),
        SLOCheck(
            name="queued_retry_attempts",
            met=(
                queued_retries
                <= policy.maximum_queued_retry_attempts
            ),
            observed=str(
                queued_retries
            ),
            target=(
                f"<={policy.maximum_queued_retry_attempts}"
            ),
        ),
    )

    score = _health_score(
        current_posture=(
            snapshot.posture.value
        ),
        unresolved_human_cases=(
            unresolved_human_cases
        ),
        queued_retries=(
            queued_retries
        ),
        healthy_percentage=(
            healthy_percentage
        ),
        healthy_streak=(
            healthy_streak
        ),
        policy=policy,
    )

    reasons = _health_reasons(
        current_posture=(
            snapshot.posture.value
        ),
        checks=checks,
    )

    status = _health_status(
        current_posture=(
            snapshot.posture.value
        ),
        unresolved_human_cases=(
            unresolved_human_cases
        ),
        checks=checks,
        score=score,
        policy=policy,
    )

    return ControlPlaneHealthReport(
        supplier_code=(
            snapshot.supplier_code
        ),
        status=status,
        score=score,
        history_runs_evaluated=(
            len(runs)
        ),
        healthy_runs=(
            healthy_runs
        ),
        healthy_run_percentage=(
            healthy_percentage
        ),
        consecutive_healthy_runs=(
            healthy_streak
        ),
        unresolved_human_cases=(
            unresolved_human_cases
        ),
        queued_retry_attempts=(
            queued_retries
        ),
        slo_checks=checks,
        reasons=reasons,
        slo_policy_fingerprint=(
            policy.fingerprint
        ),
    )


def _consecutive_healthy_runs(
    runs,
) -> int:
    """
    Runs are expected newest-first, matching run_repository.get_recent().
    """

    count = 0

    for run in runs:
        if run.posture not in HEALTHY_POSTURES:
            break

        count += 1

    return count


def _health_score(
    *,
    current_posture: str,
    unresolved_human_cases: int,
    queued_retries: int,
    healthy_percentage: float,
    healthy_streak: int,
    policy: ControlPlaneSLOPolicy,
) -> int:
    posture_points = {
        "idle": 35,
        "ready_for_approval": 32,
        "review_required": 20,
        "recovery_pending": 15,
        "blocked": 0,
        "human_attention": 0,
    }.get(
        current_posture,
        0,
    )

    backlog_points = 25

    if unresolved_human_cases > 0:
        backlog_points -= 15

    if queued_retries > 0:
        backlog_points -= 10

    backlog_points = max(
        backlog_points,
        0,
    )

    ratio_points = round(
        25
        * (
            max(
                0.0,
                min(
                    healthy_percentage,
                    100.0,
                ),
            )
            / 100.0
        )
    )

    streak_ratio = min(
        (
            healthy_streak
            / policy.minimum_consecutive_healthy_runs
        ),
        1.0,
    )

    streak_points = round(
        15
        * streak_ratio
    )

    return int(
        max(
            0,
            min(
                100,
                posture_points
                + backlog_points
                + ratio_points
                + streak_points,
            ),
        )
    )


def _health_reasons(
    *,
    current_posture: str,
    checks,
):
    reasons = []

    if current_posture in CRITICAL_POSTURES:
        reasons.append(
            HealthReason.CURRENT_POSTURE_CRITICAL
        )

    elif current_posture in DEGRADED_POSTURES:
        reasons.append(
            HealthReason.CURRENT_POSTURE_DEGRADED
        )

    by_name = {
        check.name: check
        for check in checks
    }

    if not by_name["history_depth"].met:
        reasons.append(
            HealthReason.INSUFFICIENT_HISTORY
        )

    if not by_name["healthy_run_percentage"].met:
        reasons.append(
            HealthReason
            .HEALTHY_RUN_RATIO_BELOW_TARGET
        )

    if not by_name["consecutive_healthy_runs"].met:
        reasons.append(
            HealthReason
            .HEALTHY_STREAK_BELOW_TARGET
        )

    if not by_name["unresolved_human_cases"].met:
        reasons.append(
            HealthReason.UNRESOLVED_HUMAN_CASES
        )

    if not by_name["queued_retry_attempts"].met:
        reasons.append(
            HealthReason.QUEUED_RETRIES
        )

    if not reasons:
        reasons.append(
            HealthReason.ALL_SLOS_MET
        )

    return tuple(
        reasons
    )


def _health_status(
    *,
    current_posture: str,
    unresolved_human_cases: int,
    checks,
    score: int,
    policy: ControlPlaneSLOPolicy,
) -> ControlPlaneHealthStatus:
    if (
        current_posture
        in CRITICAL_POSTURES
        or unresolved_human_cases > 0
        or score
        < policy.critical_score_threshold
    ):
        return (
            ControlPlaneHealthStatus.CRITICAL
        )

    all_slos_met = all(
        check.met
        for check in checks
    )

    if (
        current_posture
        in HEALTHY_POSTURES
        and all_slos_met
        and score
        >= policy.healthy_score_threshold
    ):
        return (
            ControlPlaneHealthStatus.HEALTHY
        )

    return (
        ControlPlaneHealthStatus.DEGRADED
    )
