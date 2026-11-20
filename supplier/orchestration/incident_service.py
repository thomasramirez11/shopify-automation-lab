from __future__ import annotations

from supplier.orchestration.incident_models import (
    HealthTransitionType,
    IncidentAction,
    IncidentEventType,
    IncidentMonitorResult,
)
from supplier.orchestration.incident_policy import (
    build_health_fingerprint,
    build_incident_id,
    classify_health_transition,
)


class SupplierIncidentMonitoringService:
    """
    Convert health observations into an incident lifecycle.

    Rules:
    - HEALTHY with no incident -> observation only.
    - DEGRADED/CRITICAL with no incident -> open incident.
    - DEGRADED -> CRITICAL -> escalate.
    - CRITICAL -> DEGRADED -> de-escalate.
    - any non-healthy -> HEALTHY -> close incident.
    - repeated same status -> no duplicate incident event.
    """

    def __init__(
        self,
        repository,
    ) -> None:
        self._repository = repository

    def record_health(
        self,
        report,
    ) -> IncidentMonitorResult:
        previous = (
            self._repository
            .get_latest_health_event(
                report.supplier_code
            )
        )

        transition = (
            classify_health_transition(
                previous_status=(
                    previous.health_status
                    if previous
                    is not None
                    else None
                ),
                current_status=(
                    report.status.value
                ),
            )
        )

        health_event = (
            self._repository
            .append_health_event(
                report=report,
                health_fingerprint=(
                    build_health_fingerprint(
                        report
                    )
                ),
                previous_event=previous,
            )
        )

        active = (
            self._repository
            .get_active_incident(
                report.supplier_code
            )
        )

        if (
            report.status.value
            == "healthy"
        ):
            if active is None:
                return IncidentMonitorResult(
                    health_event=(
                        health_event
                    ),
                    health_transition=(
                        transition
                    ),
                    incident_action=(
                        IncidentAction.NONE
                    ),
                    incident_id=None,
                    incident_event_id=None,
                )

            incident_event = (
                self._repository
                .append_incident_event(
                    incident_id=(
                        active.incident_id
                    ),
                    supplier_code=(
                        report.supplier_code
                    ),
                    source_health_event_id=(
                        health_event
                        .health_event_id
                    ),
                    event_type=(
                        IncidentEventType
                        .INCIDENT_CLOSED
                        .value
                    ),
                    health_status=(
                        report.status.value
                    ),
                    health_score=(
                        report.score
                    ),
                )
            )

            return IncidentMonitorResult(
                health_event=(
                    health_event
                ),
                health_transition=(
                    transition
                ),
                incident_action=(
                    IncidentAction.CLOSED
                ),
                incident_id=(
                    active.incident_id
                ),
                incident_event_id=(
                    incident_event
                    .incident_event_id
                ),
            )

        if active is None:
            incident_id = build_incident_id(
                supplier_code=(
                    report.supplier_code
                ),
                opening_health_event_id=(
                    health_event
                    .health_event_id
                ),
            )

            incident_event = (
                self._repository
                .append_incident_event(
                    incident_id=(
                        incident_id
                    ),
                    supplier_code=(
                        report.supplier_code
                    ),
                    source_health_event_id=(
                        health_event
                        .health_event_id
                    ),
                    event_type=(
                        IncidentEventType
                        .INCIDENT_OPENED
                        .value
                    ),
                    health_status=(
                        report.status.value
                    ),
                    health_score=(
                        report.score
                    ),
                )
            )

            return IncidentMonitorResult(
                health_event=(
                    health_event
                ),
                health_transition=(
                    transition
                ),
                incident_action=(
                    IncidentAction.OPENED
                ),
                incident_id=(
                    incident_id
                ),
                incident_event_id=(
                    incident_event
                    .incident_event_id
                ),
            )

        latest_incident_event = (
            self._repository
            .get_latest_incident_event(
                active.incident_id
            )
        )

        if (
            latest_incident_event
            is None
        ):
            raise RuntimeError(
                "Active incident has no incident events."
            )

        if (
            latest_incident_event.health_status
            == report.status.value
        ):
            return IncidentMonitorResult(
                health_event=(
                    health_event
                ),
                health_transition=(
                    transition
                ),
                incident_action=(
                    IncidentAction.NONE
                ),
                incident_id=(
                    active.incident_id
                ),
                incident_event_id=None,
            )

        if (
            latest_incident_event.health_status
            == "degraded"
            and report.status.value
            == "critical"
        ):
            event_type = (
                IncidentEventType
                .INCIDENT_ESCALATED
            )
            action = (
                IncidentAction.ESCALATED
            )

        elif (
            latest_incident_event.health_status
            == "critical"
            and report.status.value
            == "degraded"
        ):
            event_type = (
                IncidentEventType
                .INCIDENT_DEESCALATED
            )
            action = (
                IncidentAction.DEESCALATED
            )

        else:
            raise RuntimeError(
                "Unsupported active incident severity transition."
            )

        incident_event = (
            self._repository
            .append_incident_event(
                incident_id=(
                    active.incident_id
                ),
                supplier_code=(
                    report.supplier_code
                ),
                source_health_event_id=(
                    health_event
                    .health_event_id
                ),
                event_type=(
                    event_type.value
                ),
                health_status=(
                    report.status.value
                ),
                health_score=(
                    report.score
                ),
            )
        )

        return IncidentMonitorResult(
            health_event=health_event,
            health_transition=transition,
            incident_action=action,
            incident_id=(
                active.incident_id
            ),
            incident_event_id=(
                incident_event
                .incident_event_id
            ),
        )
