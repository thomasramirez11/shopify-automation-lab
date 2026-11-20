from types import SimpleNamespace

import pytest

from supplier.orchestration.health_engine import (
    evaluate_control_plane_health,
)
from supplier.orchestration.health_models import (
    ControlPlaneHealthStatus,
    ControlPlaneSLOPolicy,
    HealthReason,
)
from supplier.orchestration.models import (
    SupplierOperationsBacklog,
    SupplierSystemPosture,
)


def run(
    posture,
):
    return SimpleNamespace(
        posture=posture
    )


def snapshot(
    *,
    posture=SupplierSystemPosture.IDLE,
    human_cases=0,
    retries=0,
):
    return SimpleNamespace(
        supplier_code="demo_supplier",
        posture=posture,
        backlog=SupplierOperationsBacklog(
            queued_retry_attempts=retries,
            dead_letter_awaiting_human=(
                human_cases
            ),
        ),
    )


def default_runs():
    return [
        run("idle"),
        run("idle"),
        run("idle"),
        run("idle"),
    ]


def evaluate(
    *,
    current_snapshot=None,
    runs=None,
    policy=None,
):
    return evaluate_control_plane_health(
        snapshot=(
            current_snapshot
            or snapshot()
        ),
        recent_runs=(
            default_runs()
            if runs is None
            else runs
        ),
        policy=(
            policy
            or ControlPlaneSLOPolicy()
        ),
    )


def test_healthy_current_state_scores_100():
    report = evaluate()

    assert report.score == 100
    assert (
        report.status
        == ControlPlaneHealthStatus.HEALTHY
    )


def test_healthy_report_meets_all_slos():
    report = evaluate()

    assert report.slos_met == 5
    assert report.slo_count == 5
    assert (
        report.slo_compliance_percentage
        == 100.0
    )


def test_healthy_report_uses_all_slos_met_reason():
    report = evaluate()

    assert report.reasons == (
        HealthReason.ALL_SLOS_MET,
    )


def test_ready_for_approval_is_considered_healthy():
    report = evaluate(
        current_snapshot=snapshot(
            posture=(
                SupplierSystemPosture
                .READY_FOR_APPROVAL
            )
        )
    )

    assert (
        report.status
        == ControlPlaneHealthStatus.HEALTHY
    )
    assert report.score == 97


def test_review_required_is_degraded():
    report = evaluate(
        current_snapshot=snapshot(
            posture=(
                SupplierSystemPosture
                .REVIEW_REQUIRED
            )
        )
    )

    assert (
        report.status
        == ControlPlaneHealthStatus.DEGRADED
    )
    assert (
        HealthReason.CURRENT_POSTURE_DEGRADED
        in report.reasons
    )


def test_recovery_pending_is_degraded():
    report = evaluate(
        current_snapshot=snapshot(
            posture=(
                SupplierSystemPosture
                .RECOVERY_PENDING
            )
        )
    )

    assert (
        report.status
        == ControlPlaneHealthStatus.DEGRADED
    )


def test_human_attention_is_critical():
    report = evaluate(
        current_snapshot=snapshot(
            posture=(
                SupplierSystemPosture
                .HUMAN_ATTENTION
            ),
            human_cases=1,
        )
    )

    assert (
        report.status
        == ControlPlaneHealthStatus.CRITICAL
    )
    assert (
        HealthReason.CURRENT_POSTURE_CRITICAL
        in report.reasons
    )


def test_blocked_posture_is_critical():
    report = evaluate(
        current_snapshot=snapshot(
            posture=(
                SupplierSystemPosture.BLOCKED
            )
        )
    )

    assert (
        report.status
        == ControlPlaneHealthStatus.CRITICAL
    )


def test_unresolved_human_case_forces_critical():
    report = evaluate(
        current_snapshot=snapshot(
            posture=(
                SupplierSystemPosture.IDLE
            ),
            human_cases=1,
        )
    )

    assert (
        report.status
        == ControlPlaneHealthStatus.CRITICAL
    )
    assert (
        HealthReason.UNRESOLVED_HUMAN_CASES
        in report.reasons
    )


def test_queued_retry_causes_degraded_status():
    report = evaluate(
        current_snapshot=snapshot(
            retries=1
        )
    )

    assert (
        report.status
        == ControlPlaneHealthStatus.DEGRADED
    )
    assert (
        HealthReason.QUEUED_RETRIES
        in report.reasons
    )


def test_healthy_run_percentage_is_calculated():
    report = evaluate(
        runs=[
            run("idle"),
            run("ready_for_approval"),
            run("human_attention"),
            run("idle"),
        ]
    )

    assert (
        report.healthy_run_percentage
        == 75.0
    )
    assert report.healthy_runs == 3


def test_healthy_streak_uses_newest_first_order():
    report = evaluate(
        runs=[
            run("idle"),
            run("ready_for_approval"),
            run("human_attention"),
            run("idle"),
        ]
    )

    assert (
        report.consecutive_healthy_runs
        == 2
    )


def test_streak_stops_at_first_unhealthy_run():
    report = evaluate(
        runs=[
            run("idle"),
            run("human_attention"),
            run("idle"),
            run("idle"),
        ]
    )

    assert (
        report.consecutive_healthy_runs
        == 1
    )


def test_insufficient_history_is_degraded():
    report = evaluate(
        runs=[
            run("idle"),
        ]
    )

    assert (
        report.status
        == ControlPlaneHealthStatus.DEGRADED
    )
    assert (
        HealthReason.INSUFFICIENT_HISTORY
        in report.reasons
    )


def test_no_history_has_zero_healthy_percentage():
    report = evaluate(
        runs=[]
    )

    assert (
        report.healthy_run_percentage
        == 0.0
    )
    assert (
        report.consecutive_healthy_runs
        == 0
    )


def test_low_healthy_ratio_is_degraded():
    report = evaluate(
        runs=[
            run("idle"),
            run("human_attention"),
            run("human_attention"),
            run("idle"),
        ]
    )

    assert (
        report.status
        == ControlPlaneHealthStatus.DEGRADED
    )
    assert (
        HealthReason
        .HEALTHY_RUN_RATIO_BELOW_TARGET
        in report.reasons
    )


def test_low_healthy_streak_is_degraded():
    report = evaluate(
        runs=[
            run("idle"),
            run("human_attention"),
            run("idle"),
            run("idle"),
        ],
        policy=ControlPlaneSLOPolicy(
            minimum_healthy_run_percentage=50.0,
            minimum_consecutive_healthy_runs=2,
        ),
    )

    assert (
        report.status
        == ControlPlaneHealthStatus.DEGRADED
    )
    assert (
        HealthReason
        .HEALTHY_STREAK_BELOW_TARGET
        in report.reasons
    )


def test_history_window_limits_evaluation():
    report = evaluate(
        runs=[
            run("idle"),
            run("idle"),
            run("idle"),
            run("idle"),
            run("human_attention"),
        ],
        policy=ControlPlaneSLOPolicy(
            history_window_runs=4,
            minimum_history_runs=2,
        ),
    )

    assert (
        report.history_runs_evaluated
        == 4
    )
    assert (
        report.healthy_run_percentage
        == 100.0
    )


def test_score_is_always_within_0_to_100():
    report = evaluate(
        current_snapshot=snapshot(
            posture=(
                SupplierSystemPosture
                .HUMAN_ATTENTION
            ),
            human_cases=5,
            retries=5,
        ),
        runs=[],
    )

    assert 0 <= report.score <= 100


def test_health_policy_fingerprint_is_deterministic():
    first = ControlPlaneSLOPolicy()
    second = ControlPlaneSLOPolicy()

    assert (
        first.fingerprint
        == second.fingerprint
    )


def test_health_policy_fingerprint_changes_with_target():
    first = ControlPlaneSLOPolicy()

    second = ControlPlaneSLOPolicy(
        minimum_healthy_run_percentage=90.0
    )

    assert (
        first.fingerprint
        != second.fingerprint
    )


def test_invalid_history_window_is_rejected():
    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        ControlPlaneSLOPolicy(
            history_window_runs=0
        )


def test_minimum_history_cannot_exceed_window():
    with pytest.raises(
        ValueError,
        match="cannot exceed",
    ):
        ControlPlaneSLOPolicy(
            history_window_runs=2,
            minimum_history_runs=3,
        )


def test_invalid_percentage_is_rejected():
    with pytest.raises(
        ValueError,
        match="between 0 and 100",
    ):
        ControlPlaneSLOPolicy(
            minimum_healthy_run_percentage=101.0
        )


def test_invalid_unresolved_case_limit_is_rejected():
    with pytest.raises(
        ValueError,
        match="non-negative integer",
    ):
        ControlPlaneSLOPolicy(
            maximum_unresolved_human_cases=-1
        )


def test_invalid_score_threshold_order_is_rejected():
    with pytest.raises(
        ValueError,
        match="must be lower",
    ):
        ControlPlaneSLOPolicy(
            healthy_score_threshold=80,
            critical_score_threshold=80,
        )


def test_custom_healthy_percentage_target_can_pass():
    report = evaluate(
        runs=[
            run("idle"),
            run("idle"),
            run("human_attention"),
            run("idle"),
        ],
        policy=ControlPlaneSLOPolicy(
            minimum_healthy_run_percentage=70.0,
            minimum_consecutive_healthy_runs=2,
        ),
    )

    ratio_check = next(
        check
        for check in report.slo_checks
        if (
            check.name
            == "healthy_run_percentage"
        )
    )

    assert ratio_check.met is True


def test_slo_checks_expose_observed_and_target_values():
    report = evaluate()

    history_check = next(
        check
        for check in report.slo_checks
        if check.name == "history_depth"
    )

    assert history_check.observed == "4"
    assert history_check.target == ">=2"
