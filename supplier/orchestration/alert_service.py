from __future__ import annotations

from supplier.orchestration.alert_models import (
    IncidentAlertRoutingResult,
    IncidentAlertScanResult,
)
from supplier.orchestration.alert_policy import (
    DEFAULT_INCIDENT_ALERT_ROUTING_POLICY,
    build_alert_route_fingerprint,
    evaluate_incident_alert_routing,
)


class SupplierIncidentAlertRoutingService:
    """
    Route incident events into immutable alert intents.

    This service still does not deliver external notifications.
    """

    def __init__(
        self,
        *,
        incident_repository,
        alert_repository,
        policy=(
            DEFAULT_INCIDENT_ALERT_ROUTING_POLICY
        ),
    ) -> None:
        self._incident_repository = (
            incident_repository
        )
        self._alert_repository = (
            alert_repository
        )
        self._policy = policy

    def route_incident_event(
        self,
        incident_event,
    ) -> IncidentAlertRoutingResult:
        decision = (
            evaluate_incident_alert_routing(
                incident_event=(
                    incident_event
                ),
                policy=(
                    self._policy
                ),
            )
        )

        stored_routes = []
        routes_written = 0
        routes_already_recorded = 0

        for route in decision.routes:
            stored, created = (
                self._alert_repository
                .append_route(
                    decision=decision,
                    route=route,
                    route_fingerprint=(
                        build_alert_route_fingerprint(
                            decision=decision,
                            route=route,
                        )
                    ),
                )
            )

            stored_routes.append(
                stored
            )

            if created:
                routes_written += 1
            else:
                routes_already_recorded += 1

        return IncidentAlertRoutingResult(
            decision=decision,
            routes_planned=(
                len(decision.routes)
            ),
            routes_written=(
                routes_written
            ),
            routes_already_recorded=(
                routes_already_recorded
            ),
            stored_routes=tuple(
                stored_routes
            ),
        )

    def route_existing_incidents(
        self,
        *,
        supplier_code: str,
        limit: int = 20,
    ) -> IncidentAlertScanResult:
        incidents = (
            self._incident_repository
            .get_incident_summaries(
                supplier_code=supplier_code,
                limit=limit,
            )
        )

        incident_events_seen = 0
        routing_decisions = 0
        routes_planned = 0
        routes_written = 0
        routes_already_recorded = 0

        for incident in incidents:
            events = (
                self._incident_repository
                .get_incident_events(
                    incident.incident_id
                )
            )

            for event in events:
                incident_events_seen += 1

                result = (
                    self.route_incident_event(
                        event
                    )
                )

                routing_decisions += 1
                routes_planned += (
                    result.routes_planned
                )
                routes_written += (
                    result.routes_written
                )
                routes_already_recorded += (
                    result
                    .routes_already_recorded
                )

        return IncidentAlertScanResult(
            incidents_seen=(
                len(incidents)
            ),
            incident_events_seen=(
                incident_events_seen
            ),
            routing_decisions=(
                routing_decisions
            ),
            routes_planned=(
                routes_planned
            ),
            routes_written=(
                routes_written
            ),
            routes_already_recorded=(
                routes_already_recorded
            ),
        )
