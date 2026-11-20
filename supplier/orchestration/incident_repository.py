from __future__ import annotations

import json
from datetime import datetime

from database.connection import (
    get_db_connection,
)
from database.supplier_incident_schema import (
    ensure_supplier_incident_schema,
)
from supplier.orchestration.incident_models import (
    IncidentSummary,
    StoredHealthEvent,
    StoredIncidentEvent,
)


class SupplierIncidentRepository:
    """
    Append-only health and incident persistence.
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
            ensure_supplier_incident_schema(
                connection
            )

    def append_health_event(
        self,
        *,
        report,
        health_fingerprint: str,
        previous_event: StoredHealthEvent | None,
    ) -> StoredHealthEvent:
        with self._connection_factory() as connection:
            ensure_supplier_incident_schema(
                connection
            )

            cursor = connection.execute(
                """
                INSERT INTO supplier_health_events (
                    supplier_code,
                    health_fingerprint,
                    health_status,
                    health_score,
                    slo_compliance_percentage,
                    slos_met,
                    slo_count,
                    history_runs_evaluated,
                    healthy_run_percentage,
                    consecutive_healthy_runs,
                    unresolved_human_cases,
                    queued_retry_attempts,
                    reasons_json,
                    slo_policy_fingerprint,
                    previous_health_event_id,
                    previous_health_status,
                    status_changed
                )
                VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?, ?
                );
                """,
                (
                    report.supplier_code,
                    health_fingerprint,
                    report.status.value,
                    report.score,
                    report.slo_compliance_percentage,
                    report.slos_met,
                    report.slo_count,
                    report.history_runs_evaluated,
                    report.healthy_run_percentage,
                    report.consecutive_healthy_runs,
                    report.unresolved_human_cases,
                    report.queued_retry_attempts,
                    json.dumps(
                        [
                            reason.value
                            for reason
                            in report.reasons
                        ],
                        separators=(",", ":"),
                    ),
                    report.slo_policy_fingerprint,
                    (
                        previous_event.health_event_id
                        if previous_event
                        is not None
                        else None
                    ),
                    (
                        previous_event.health_status
                        if previous_event
                        is not None
                        else None
                    ),
                    int(
                        previous_event is not None
                        and previous_event.health_status
                        != report.status.value
                    ),
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM supplier_health_events
                WHERE health_event_id = ?;
                """,
                (
                    cursor.lastrowid,
                ),
            ).fetchone()

            return StoredHealthEvent(
                **dict(row)
            )

    def get_latest_health_event(
        self,
        supplier_code: str,
    ) -> StoredHealthEvent | None:
        with self._connection_factory() as connection:
            ensure_supplier_incident_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT *
                FROM supplier_health_events
                WHERE supplier_code = ?
                ORDER BY health_event_id DESC
                LIMIT 1;
                """,
                (
                    supplier_code,
                ),
            ).fetchone()

            if row is None:
                return None

            return StoredHealthEvent(
                **dict(row)
            )

    def get_recent_health_events(
        self,
        *,
        supplier_code: str,
        limit: int = 20,
    ) -> list[StoredHealthEvent]:
        _validate_limit(
            limit
        )

        with self._connection_factory() as connection:
            ensure_supplier_incident_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT *
                FROM supplier_health_events
                WHERE supplier_code = ?
                ORDER BY health_event_id DESC
                LIMIT ?;
                """,
                (
                    supplier_code,
                    limit,
                ),
            ).fetchall()

            return [
                StoredHealthEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def count_health_events(
        self,
        supplier_code: str,
    ) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_incident_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplier_health_events
                WHERE supplier_code = ?;
                """,
                (
                    supplier_code,
                ),
            ).fetchone()

            return int(
                row["count"]
            )

    def append_incident_event(
        self,
        *,
        incident_id: str,
        supplier_code: str,
        source_health_event_id: int,
        event_type: str,
        health_status: str,
        health_score: int,
    ) -> StoredIncidentEvent:
        with self._connection_factory() as connection:
            ensure_supplier_incident_schema(
                connection
            )

            cursor = connection.execute(
                """
                INSERT INTO supplier_incident_events (
                    incident_id,
                    supplier_code,
                    source_health_event_id,
                    event_type,
                    health_status,
                    health_score
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?
                );
                """,
                (
                    incident_id,
                    supplier_code,
                    source_health_event_id,
                    event_type,
                    health_status,
                    health_score,
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM supplier_incident_events
                WHERE incident_event_id = ?;
                """,
                (
                    cursor.lastrowid,
                ),
            ).fetchone()

            return StoredIncidentEvent(
                **dict(row)
            )

    def get_latest_incident_event(
        self,
        incident_id: str,
    ) -> StoredIncidentEvent | None:
        with self._connection_factory() as connection:
            ensure_supplier_incident_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT *
                FROM supplier_incident_events
                WHERE incident_id = ?
                ORDER BY incident_event_id DESC
                LIMIT 1;
                """,
                (
                    incident_id,
                ),
            ).fetchone()

            if row is None:
                return None

            return StoredIncidentEvent(
                **dict(row)
            )

    def get_incident_events(
        self,
        incident_id: str,
    ) -> list[StoredIncidentEvent]:
        with self._connection_factory() as connection:
            ensure_supplier_incident_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT *
                FROM supplier_incident_events
                WHERE incident_id = ?
                ORDER BY incident_event_id;
                """,
                (
                    incident_id,
                ),
            ).fetchall()

            return [
                StoredIncidentEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def get_active_incident(
        self,
        supplier_code: str,
    ) -> IncidentSummary | None:
        with self._connection_factory() as connection:
            ensure_supplier_incident_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT opened.incident_id
                FROM supplier_incident_events AS opened

                WHERE opened.supplier_code = ?
                  AND opened.event_type = 'incident_opened'

                  AND NOT EXISTS (
                      SELECT 1
                      FROM supplier_incident_events AS closed
                      WHERE closed.incident_id = opened.incident_id
                        AND closed.event_type = 'incident_closed'
                  )

                ORDER BY opened.incident_event_id DESC
                LIMIT 1;
                """,
                (
                    supplier_code,
                ),
            ).fetchone()

            if row is None:
                return None

            return self._summary_by_id_with_connection(
                connection,
                row["incident_id"],
            )

    def get_incident_summaries(
        self,
        *,
        supplier_code: str,
        limit: int = 20,
    ) -> list[IncidentSummary]:
        _validate_limit(
            limit
        )

        with self._connection_factory() as connection:
            ensure_supplier_incident_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT incident_id
                FROM supplier_incident_events
                WHERE supplier_code = ?
                  AND event_type = 'incident_opened'
                ORDER BY incident_event_id DESC
                LIMIT ?;
                """,
                (
                    supplier_code,
                    limit,
                ),
            ).fetchall()

            return [
                self._summary_by_id_with_connection(
                    connection,
                    row["incident_id"],
                )
                for row in rows
            ]

    def count_incidents(
        self,
        supplier_code: str,
    ) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_incident_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplier_incident_events
                WHERE supplier_code = ?
                  AND event_type = 'incident_opened';
                """,
                (
                    supplier_code,
                ),
            ).fetchone()

            return int(
                row["count"]
            )

    def count_open_incidents(
        self,
        supplier_code: str,
    ) -> int:
        return sum(
            1
            for incident
            in self.get_incident_summaries(
                supplier_code=supplier_code,
                limit=10000,
            )
            if incident.status == "open"
        )

    def mean_time_to_recovery_seconds(
        self,
        supplier_code: str,
    ) -> float | None:
        durations = [
            incident.duration_seconds
            for incident
            in self.get_incident_summaries(
                supplier_code=supplier_code,
                limit=10000,
            )
            if incident.duration_seconds
            is not None
        ]

        if not durations:
            return None

        return round(
            sum(durations)
            / len(durations),
            2,
        )

    def _summary_by_id_with_connection(
        self,
        connection,
        incident_id: str,
    ) -> IncidentSummary:
        opened = connection.execute(
            """
            SELECT *
            FROM supplier_incident_events
            WHERE incident_id = ?
              AND event_type = 'incident_opened'
            LIMIT 1;
            """,
            (
                incident_id,
            ),
        ).fetchone()

        if opened is None:
            raise RuntimeError(
                "Incident summary requested without an opening event."
            )

        latest = connection.execute(
            """
            SELECT *
            FROM supplier_incident_events
            WHERE incident_id = ?
            ORDER BY incident_event_id DESC
            LIMIT 1;
            """,
            (
                incident_id,
            ),
        ).fetchone()

        closed = connection.execute(
            """
            SELECT *
            FROM supplier_incident_events
            WHERE incident_id = ?
              AND event_type = 'incident_closed'
            LIMIT 1;
            """,
            (
                incident_id,
            ),
        ).fetchone()

        closed_at = (
            closed["created_at"]
            if closed is not None
            else None
        )

        duration = (
            _duration_seconds(
                opened["created_at"],
                closed_at,
            )
            if closed_at is not None
            else None
        )

        return IncidentSummary(
            incident_id=(
                opened["incident_id"]
            ),
            supplier_code=(
                opened["supplier_code"]
            ),
            opening_health_status=(
                opened["health_status"]
            ),
            latest_health_status=(
                latest["health_status"]
            ),
            latest_event_type=(
                latest["event_type"]
            ),
            opened_at=(
                opened["created_at"]
            ),
            closed_at=closed_at,
            duration_seconds=duration,
        )


def _validate_limit(
    limit: int,
) -> None:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit <= 0
    ):
        raise ValueError(
            "limit must be a positive integer."
        )


def _duration_seconds(
    opened_at: str,
    closed_at: str,
) -> float:
    opened = datetime.fromisoformat(
        opened_at
    )
    closed = datetime.fromisoformat(
        closed_at
    )

    return max(
        0.0,
        (
            closed
            - opened
        ).total_seconds(),
    )
