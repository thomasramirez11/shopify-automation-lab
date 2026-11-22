from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from supplier.orchestration.alert_models import (
    AlertRoutingError,
    IncidentAlertDecision,
    IncidentAlertRoute,
    IncidentAlertSeverity,
)


@dataclass(frozen=True)
class IncidentAlertRoutingPolicy:
    """
    Routing rules. Still no external delivery.

    Degraded incident:
        dashboard + operator review

    Critical incident:
        dashboard + operator review + immediate alert

    Recovery:
        dashboard + recovery notice
    """

    degraded_routes: tuple[
        IncidentAlertRoute,
        ...,
    ] = (
        IncidentAlertRoute.DASHBOARD,
        IncidentAlertRoute.OPERATOR_REVIEW,
    )

    critical_routes: tuple[
        IncidentAlertRoute,
        ...,
    ] = (
        IncidentAlertRoute.DASHBOARD,
        IncidentAlertRoute.OPERATOR_REVIEW,
        IncidentAlertRoute.IMMEDIATE_ALERT,
    )

    recovery_routes: tuple[
        IncidentAlertRoute,
        ...,
    ] = (
        IncidentAlertRoute.DASHBOARD,
        IncidentAlertRoute.RECOVERY_NOTICE,
    )

    def __post_init__(self) -> None:
        for field_name in (
            "degraded_routes",
            "critical_routes",
            "recovery_routes",
        ):
            routes = getattr(
                self,
                field_name,
            )

            if (
                not isinstance(
                    routes,
                    tuple,
                )
                or not routes
            ):
                raise AlertRoutingError(
                    f"{field_name} must be a non-empty tuple."
                )

            if len(set(routes)) != len(routes):
                raise AlertRoutingError(
                    f"{field_name} cannot contain duplicate routes."
                )

            if not all(
                isinstance(
                    route,
                    IncidentAlertRoute,
                )
                for route in routes
            ):
                raise AlertRoutingError(
                    f"{field_name} must contain IncidentAlertRoute values."
                )

    @property
    def fingerprint(self) -> str:
        payload = {
            "degraded_routes": [
                route.value
                for route in self.degraded_routes
            ],
            "critical_routes": [
                route.value
                for route in self.critical_routes
            ],
            "recovery_routes": [
                route.value
                for route in self.recovery_routes
            ],
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


DEFAULT_INCIDENT_ALERT_ROUTING_POLICY = (
    IncidentAlertRoutingPolicy()
)


def evaluate_incident_alert_routing(
    *,
    incident_event,
    policy: IncidentAlertRoutingPolicy = (
        DEFAULT_INCIDENT_ALERT_ROUTING_POLICY
    ),
) -> IncidentAlertDecision:
    event_type = (
        incident_event.event_type
    )

    health_status = (
        incident_event.health_status
    )

    if event_type == "incident_closed":
        severity = (
            IncidentAlertSeverity.INFO
        )
        routes = (
            policy.recovery_routes
        )
        reason = (
            "incident_recovered"
        )

    elif health_status == "critical":
        severity = (
            IncidentAlertSeverity.CRITICAL
        )
        routes = (
            policy.critical_routes
        )

        reason = (
            "critical_incident"
            if event_type
            == "incident_opened"
            else "incident_escalated_to_critical"
        )

    elif health_status == "degraded":
        severity = (
            IncidentAlertSeverity.WARNING
        )
        routes = (
            policy.degraded_routes
        )

        reason = (
            "degraded_incident"
            if event_type
            == "incident_opened"
            else "incident_deescalated_but_still_open"
        )

    else:
        raise AlertRoutingError(
            "Unsupported incident event for alert routing: "
            f"{event_type!r} / {health_status!r}"
        )

    return IncidentAlertDecision(
        incident_id=(
            incident_event.incident_id
        ),
        source_incident_event_id=(
            incident_event
            .incident_event_id
        ),
        supplier_code=(
            incident_event.supplier_code
        ),
        source_event_type=(
            event_type
        ),
        source_health_status=(
            health_status
        ),
        severity=severity,
        routes=routes,
        reason=reason,
        policy_fingerprint=(
            policy.fingerprint
        ),
    )


def build_alert_route_fingerprint(
    *,
    decision: IncidentAlertDecision,
    route: IncidentAlertRoute,
) -> str:
    """
    Identity of the route itself.

    The policy fingerprint is intentionally not part of this identity:
    the same incident event should not send the same route twice merely
    because the routing policy was later re-evaluated.
    """

    payload = {
        "incident_id":
            decision.incident_id,
        "source_incident_event_id":
            decision.source_incident_event_id,
        "route":
            route.value,
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
