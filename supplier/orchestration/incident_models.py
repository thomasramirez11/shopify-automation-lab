from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IncidentError(ValueError):
    """Raised when incident/health event data is invalid."""


class HealthTransitionType(str, Enum):
    INITIAL = "initial"
    UNCHANGED = "unchanged"

    HEALTH_DEGRADED = "health_degraded"
    HEALTH_CRITICAL = "health_critical"

    HEALTH_ESCALATED = "health_escalated"
    HEALTH_IMPROVED = "health_improved"
    HEALTH_RECOVERED = "health_recovered"


class IncidentEventType(str, Enum):
    INCIDENT_OPENED = "incident_opened"
    INCIDENT_ESCALATED = "incident_escalated"
    INCIDENT_DEESCALATED = "incident_deescalated"
    INCIDENT_CLOSED = "incident_closed"


class IncidentAction(str, Enum):
    NONE = "none"
    OPENED = "opened"
    ESCALATED = "escalated"
    DEESCALATED = "deescalated"
    CLOSED = "closed"


@dataclass(frozen=True)
class StoredHealthEvent:
    health_event_id: int

    supplier_code: str

    health_fingerprint: str
    health_status: str
    health_score: int

    slo_compliance_percentage: float
    slos_met: int
    slo_count: int

    history_runs_evaluated: int
    healthy_run_percentage: float
    consecutive_healthy_runs: int

    unresolved_human_cases: int
    queued_retry_attempts: int

    reasons_json: str
    slo_policy_fingerprint: str

    previous_health_event_id: int | None
    previous_health_status: str | None
    status_changed: int

    created_at: str


@dataclass(frozen=True)
class StoredIncidentEvent:
    incident_event_id: int

    incident_id: str
    supplier_code: str
    source_health_event_id: int

    event_type: str
    health_status: str
    health_score: int

    created_at: str


@dataclass(frozen=True)
class IncidentSummary:
    incident_id: str
    supplier_code: str

    opening_health_status: str
    latest_health_status: str
    latest_event_type: str

    opened_at: str
    closed_at: str | None

    duration_seconds: float | None

    @property
    def status(self) -> str:
        return (
            "closed"
            if self.closed_at is not None
            else "open"
        )


@dataclass(frozen=True)
class IncidentMonitorResult:
    health_event: StoredHealthEvent

    health_transition: HealthTransitionType
    incident_action: IncidentAction

    incident_id: str | None
    incident_event_id: int | None
