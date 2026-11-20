from __future__ import annotations

from supplier.orchestration.health_models import (
    ControlPlaneSLOPolicy,
)


DEFAULT_CONTROL_PLANE_SLO_POLICY = (
    ControlPlaneSLOPolicy(
        history_window_runs=4,
        minimum_history_runs=2,
        minimum_healthy_run_percentage=75.0,
        minimum_consecutive_healthy_runs=2,
        maximum_unresolved_human_cases=0,
        maximum_queued_retry_attempts=0,
        healthy_score_threshold=85,
        critical_score_threshold=40,
    )
)
