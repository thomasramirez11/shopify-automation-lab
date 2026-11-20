from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum


class ControlPlaneHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class HealthReason(str, Enum):
    ALL_SLOS_MET = "all_slos_met"
    INSUFFICIENT_HISTORY = "insufficient_history"
    HEALTHY_RUN_RATIO_BELOW_TARGET = (
        "healthy_run_ratio_below_target"
    )
    HEALTHY_STREAK_BELOW_TARGET = (
        "healthy_streak_below_target"
    )
    UNRESOLVED_HUMAN_CASES = (
        "unresolved_human_cases"
    )
    QUEUED_RETRIES = "queued_retries"
    CURRENT_POSTURE_DEGRADED = (
        "current_posture_degraded"
    )
    CURRENT_POSTURE_CRITICAL = (
        "current_posture_critical"
    )


@dataclass(frozen=True)
class ControlPlaneSLOPolicy:
    """
    Internal reliability objectives for the supplier control plane.

    These are operational targets, not customer-facing guarantees.
    """

    history_window_runs: int = 4
    minimum_history_runs: int = 2

    minimum_healthy_run_percentage: float = 75.0
    minimum_consecutive_healthy_runs: int = 2

    maximum_unresolved_human_cases: int = 0
    maximum_queued_retry_attempts: int = 0

    healthy_score_threshold: int = 85
    critical_score_threshold: int = 40

    def __post_init__(self) -> None:
        integer_positive_fields = (
            "history_window_runs",
            "minimum_history_runs",
            "minimum_consecutive_healthy_runs",
        )

        for field_name in integer_positive_fields:
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

        if (
            self.minimum_history_runs
            > self.history_window_runs
        ):
            raise ValueError(
                "minimum_history_runs cannot exceed history_window_runs."
            )

        if (
            isinstance(
                self.minimum_healthy_run_percentage,
                bool,
            )
            or not isinstance(
                self.minimum_healthy_run_percentage,
                (int, float),
            )
            or not (
                0.0
                <= float(
                    self.minimum_healthy_run_percentage
                )
                <= 100.0
            )
        ):
            raise ValueError(
                "minimum_healthy_run_percentage must be between 0 and 100."
            )

        non_negative_fields = (
            "maximum_unresolved_human_cases",
            "maximum_queued_retry_attempts",
        )

        for field_name in non_negative_fields:
            value = getattr(
                self,
                field_name,
            )

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(
                    f"{field_name} must be a non-negative integer."
                )

        score_fields = (
            "healthy_score_threshold",
            "critical_score_threshold",
        )

        for field_name in score_fields:
            value = getattr(
                self,
                field_name,
            )

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not (
                    0
                    <= value
                    <= 100
                )
            ):
                raise ValueError(
                    f"{field_name} must be an integer between 0 and 100."
                )

        if (
            self.critical_score_threshold
            >= self.healthy_score_threshold
        ):
            raise ValueError(
                "critical_score_threshold must be lower than healthy_score_threshold."
            )

    @property
    def fingerprint(self) -> str:
        payload = {
            "history_window_runs":
                self.history_window_runs,
            "minimum_history_runs":
                self.minimum_history_runs,
            "minimum_healthy_run_percentage":
                float(
                    self.minimum_healthy_run_percentage
                ),
            "minimum_consecutive_healthy_runs":
                self.minimum_consecutive_healthy_runs,
            "maximum_unresolved_human_cases":
                self.maximum_unresolved_human_cases,
            "maximum_queued_retry_attempts":
                self.maximum_queued_retry_attempts,
            "healthy_score_threshold":
                self.healthy_score_threshold,
            "critical_score_threshold":
                self.critical_score_threshold,
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
class SLOCheck:
    name: str
    met: bool
    observed: str
    target: str


@dataclass(frozen=True)
class ControlPlaneHealthReport:
    supplier_code: str

    status: ControlPlaneHealthStatus
    score: int

    history_runs_evaluated: int
    healthy_runs: int
    healthy_run_percentage: float
    consecutive_healthy_runs: int

    unresolved_human_cases: int
    queued_retry_attempts: int

    slo_checks: tuple[SLOCheck, ...]
    reasons: tuple[HealthReason, ...]

    slo_policy_fingerprint: str

    @property
    def slos_met(self) -> int:
        return sum(
            1
            for check in self.slo_checks
            if check.met
        )

    @property
    def slo_count(self) -> int:
        return len(
            self.slo_checks
        )

    @property
    def slo_compliance_percentage(self) -> float:
        if not self.slo_checks:
            return 100.0

        return round(
            (
                self.slos_met
                / self.slo_count
            )
            * 100.0,
            1,
        )
