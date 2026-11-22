from __future__ import annotations

from database.connection import (
    get_db_connection,
)
from database.supplier_incident_alert_schema import (
    ensure_supplier_incident_alert_schema,
)
from supplier.orchestration.alert_models import (
    StoredIncidentAlertRoute,
)


class SupplierIncidentAlertRepository:
    """
    Append-only persistence for alert-routing decisions.
    """

    def __init__(
        self,
        *,
        connection_factory=get_db_connection,
    ) -> None:
        self._connection_factory = (
            connection_factory
        )

    def ensure_schema(
        self,
    ) -> None:
        with self._connection_factory() as connection:
            ensure_supplier_incident_alert_schema(
                connection
            )

    def append_route(
        self,
        *,
        decision,
        route,
        route_fingerprint: str,
    ) -> tuple[
        StoredIncidentAlertRoute,
        bool,
    ]:
        with self._connection_factory() as connection:
            ensure_supplier_incident_alert_schema(
                connection
            )

            cursor = connection.execute(
                """
                INSERT INTO supplier_incident_alert_routes (
                    incident_id,
                    source_incident_event_id,
                    supplier_code,
                    source_event_type,
                    severity,
                    route,
                    policy_fingerprint,
                    route_fingerprint
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT (
                    incident_id,
                    source_incident_event_id,
                    route
                )
                DO NOTHING;
                """,
                (
                    decision.incident_id,
                    decision.source_incident_event_id,
                    decision.supplier_code,
                    decision.source_event_type,
                    decision.severity.value,
                    route.value,
                    decision.policy_fingerprint,
                    route_fingerprint,
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM supplier_incident_alert_routes
                WHERE incident_id = ?
                  AND source_incident_event_id = ?
                  AND route = ?;
                """,
                (
                    decision.incident_id,
                    decision.source_incident_event_id,
                    route.value,
                ),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "Alert route could not be read after append."
                )

            return (
                StoredIncidentAlertRoute(
                    **dict(row)
                ),
                cursor.rowcount == 1,
            )

    def get_routes_for_incident(
        self,
        incident_id: str,
    ) -> list[StoredIncidentAlertRoute]:
        with self._connection_factory() as connection:
            ensure_supplier_incident_alert_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT *
                FROM supplier_incident_alert_routes
                WHERE incident_id = ?
                ORDER BY route_event_id;
                """,
                (
                    incident_id,
                ),
            ).fetchall()

            return [
                StoredIncidentAlertRoute(
                    **dict(row)
                )
                for row in rows
            ]

    def get_recent_routes(
        self,
        *,
        supplier_code: str,
        limit: int = 50,
    ) -> list[StoredIncidentAlertRoute]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
        ):
            raise ValueError(
                "limit must be a positive integer."
            )

        with self._connection_factory() as connection:
            ensure_supplier_incident_alert_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT *
                FROM supplier_incident_alert_routes
                WHERE supplier_code = ?
                ORDER BY route_event_id DESC
                LIMIT ?;
                """,
                (
                    supplier_code,
                    limit,
                ),
            ).fetchall()

            return [
                StoredIncidentAlertRoute(
                    **dict(row)
                )
                for row in rows
            ]

    def count_routes(
        self,
        supplier_code: str,
    ) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_incident_alert_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplier_incident_alert_routes
                WHERE supplier_code = ?;
                """,
                (
                    supplier_code,
                ),
            ).fetchone()

            return int(
                row["count"]
            )

    def count_routes_by_severity(
        self,
        *,
        supplier_code: str,
        severity: str,
    ) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_incident_alert_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplier_incident_alert_routes
                WHERE supplier_code = ?
                  AND severity = ?;
                """,
                (
                    supplier_code,
                    severity,
                ),
            ).fetchone()

            return int(
                row["count"]
            )
