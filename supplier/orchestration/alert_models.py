from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AlertRoutingError(ValueError):
    """Raised when incident alert routing input is invalid."""


class IncidentAlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class IncidentAlertRoute(str, Enum):
    DASHBOARD = "dashboard"
    OPERATOR_REVIEW = "operator_review"
    IMMEDIATE_ALERT = "immediate_alert"
    RECOVERY_NOTICE = "recovery_notice"


@dataclass(frozen=True)
class IncidentAlertDecision:
    incident_id: str
    source_incident_event_id: int
    supplier_code: str

    source_event_type: str
    source_health_status: str

    severity: IncidentAlertSeverity

    routes: tuple[
        IncidentAlertRoute,
        ...,
    ]

    reason: str
    policy_fingerprint: str


@dataclass(frozen=True)
class StoredIncidentAlertRoute:
    route_event_id: int

    incident_id: str
    source_incident_event_id: int
    supplier_code: str

    source_event_type: str
    severity: str
    route: str

    policy_fingerprint: str
    route_fingerprint: str

    created_at: str


@dataclass(frozen=True)
class IncidentAlertRoutingResult:
    decision: IncidentAlertDecision

    routes_planned: int
    routes_written: int
    routes_already_recorded: int

    stored_routes: tuple[
        StoredIncidentAlertRoute,
        ...,
    ]


@dataclass(frozen=True)
class IncidentAlertScanResult:
    incidents_seen: int
    incident_events_seen: int

    routing_decisions: int

    routes_planned: int
    routes_written: int
    routes_already_recorded: int
