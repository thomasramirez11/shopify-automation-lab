from __future__ import annotations

import hashlib
import json

from supplier.orchestration.incident_models import (
    HealthTransitionType,
)


def build_health_fingerprint(
    report,
) -> str:
    """
    Content identity for one health evaluation.

    Repeated identical observations may still be stored as separate events;
    the fingerprint tells us their content was the same.
    """

    payload = {
        "supplier_code":
            report.supplier_code,
        "health_status":
            report.status.value,
        "health_score":
            report.score,
        "history_runs_evaluated":
            report.history_runs_evaluated,
        "healthy_runs":
            report.healthy_runs,
        "healthy_run_percentage":
            report.healthy_run_percentage,
        "consecutive_healthy_runs":
            report.consecutive_healthy_runs,
        "unresolved_human_cases":
            report.unresolved_human_cases,
        "queued_retry_attempts":
            report.queued_retry_attempts,
        "slo_compliance_percentage":
            report.slo_compliance_percentage,
        "slos_met":
            report.slos_met,
        "slo_count":
            report.slo_count,
        "reasons": [
            reason.value
            for reason in report.reasons
        ],
        "slo_checks": [
            {
                "name": check.name,
                "met": check.met,
                "observed": check.observed,
                "target": check.target,
            }
            for check in report.slo_checks
        ],
        "slo_policy_fingerprint":
            report.slo_policy_fingerprint,
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


def build_incident_id(
    *,
    supplier_code: str,
    opening_health_event_id: int,
) -> str:
    payload = (
        "supplier-incident:"
        + supplier_code
        + ":"
        + str(
            opening_health_event_id
        )
    )

    return hashlib.sha256(
        payload.encode(
            "utf-8"
        )
    ).hexdigest()


def classify_health_transition(
    *,
    previous_status: str | None,
    current_status: str,
) -> HealthTransitionType:
    if previous_status is None:
        return (
            HealthTransitionType.INITIAL
        )

    if previous_status == current_status:
        return (
            HealthTransitionType.UNCHANGED
        )

    if (
        previous_status == "healthy"
        and current_status == "degraded"
    ):
        return (
            HealthTransitionType
            .HEALTH_DEGRADED
        )

    if (
        previous_status == "healthy"
        and current_status == "critical"
    ):
        return (
            HealthTransitionType
            .HEALTH_CRITICAL
        )

    if (
        previous_status == "degraded"
        and current_status == "critical"
    ):
        return (
            HealthTransitionType
            .HEALTH_ESCALATED
        )

    if (
        previous_status == "critical"
        and current_status == "degraded"
    ):
        return (
            HealthTransitionType
            .HEALTH_IMPROVED
        )

    if (
        previous_status in {
            "degraded",
            "critical",
        }
        and current_status == "healthy"
    ):
        return (
            HealthTransitionType
            .HEALTH_RECOVERED
        )

    raise ValueError(
        "Unsupported health transition: "
        f"{previous_status!r} -> {current_status!r}"
    )
