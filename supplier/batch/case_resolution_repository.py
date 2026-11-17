from __future__ import annotations

from database.connection import (
    get_db_connection,
)
from database.supplier_case_resolution_schema import (
    ensure_supplier_case_resolution_schema,
)
from supplier.batch.case_resolution_models import (
    AcknowledgedDeadLetterCase,
    CaseResolutionEvent,
    CaseResolutionView,
    ResolutionAppendResult,
    StoredCaseResolutionEvent,
)


class SupplierCaseResolutionRepository:
    """
    Append-only persistence and lifecycle queries for human-resolved DLQ cases.
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
            ensure_supplier_case_resolution_schema(
                connection
            )

    def get_acknowledged_case(
        self,
        case_id: str,
    ):
        with self._connection_factory() as connection:
            ensure_supplier_case_resolution_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT
                    opened.case_id,
                    opened.source_retry_id,
                    opened.source_batch_id,
                    opened.operation_id,
                    opened.shopify_variant_id,
                    opened.shopify_sku,
                    opened.requested_quantity,
                    opened.reason_code,

                    acknowledged.actor
                        AS acknowledged_by,

                    acknowledged.note
                        AS acknowledgement_note

                FROM supplier_dead_letter_events AS opened

                JOIN supplier_dead_letter_events AS acknowledged
                  ON acknowledged.case_id = opened.case_id
                 AND acknowledged.event_type = 'case_acknowledged'

                WHERE opened.case_id = ?
                  AND opened.event_type = 'case_opened'

                LIMIT 1;
                """,
                (
                    case_id,
                ),
            ).fetchone()

            if row is None:
                return None

            return AcknowledgedDeadLetterCase(
                **dict(row)
            )

    def append(
        self,
        event: CaseResolutionEvent,
    ) -> ResolutionAppendResult:
        with self._connection_factory() as connection:
            ensure_supplier_case_resolution_schema(
                connection
            )

            cursor = connection.execute(
                """
                INSERT INTO supplier_case_resolution_events (
                    case_id,
                    resolution_fingerprint,
                    event_type,
                    resolution_code,
                    actor,
                    note,
                    shopify_variant_id,
                    shopify_sku,
                    requested_quantity,
                    error_message
                )
                VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?
                )
                ON CONFLICT(
                    case_id,
                    event_type
                )
                DO NOTHING;
                """,
                (
                    event.case_id,
                    event.resolution_fingerprint,
                    event.event_type.value,
                    event.resolution_code.value,
                    event.actor,
                    event.note,
                    event.shopify_variant_id,
                    event.shopify_sku,
                    event.requested_quantity,
                    event.error_message,
                ),
            )

            row = connection.execute(
                """
                SELECT resolution_event_id
                FROM supplier_case_resolution_events
                WHERE case_id = ?
                  AND event_type = ?;
                """,
                (
                    event.case_id,
                    event.event_type.value,
                ),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "Case resolution event could not be read after append."
                )

            return ResolutionAppendResult(
                resolution_event_id=(
                    row["resolution_event_id"]
                ),
                created_new=(
                    cursor.rowcount == 1
                ),
            )

    def get_events(
        self,
        case_id: str,
    ) -> list[StoredCaseResolutionEvent]:
        with self._connection_factory() as connection:
            ensure_supplier_case_resolution_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    resolution_event_id,
                    case_id,
                    resolution_fingerprint,
                    event_type,
                    resolution_code,
                    actor,
                    note,
                    shopify_variant_id,
                    shopify_sku,
                    requested_quantity,
                    error_message,
                    created_at
                FROM supplier_case_resolution_events
                WHERE case_id = ?
                ORDER BY resolution_event_id;
                """,
                (
                    case_id,
                ),
            ).fetchall()

            return [
                StoredCaseResolutionEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def get_event(
        self,
        *,
        case_id: str,
        event_type: str,
    ):
        events = self.get_events(
            case_id
        )

        for event in events:
            if event.event_type == event_type:
                return event

        return None

    def get_cases(
        self,
        *,
        limit: int = 20,
    ) -> list[CaseResolutionView]:
        if (
            isinstance(
                limit,
                bool,
            )
            or not isinstance(
                limit,
                int,
            )
            or limit <= 0
        ):
            raise ValueError(
                "limit must be a positive integer."
            )

        with self._connection_factory() as connection:
            ensure_supplier_case_resolution_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    recorded.case_id,
                    recorded.shopify_sku,
                    recorded.requested_quantity,
                    recorded.resolution_code,
                    recorded.resolution_fingerprint,
                    recorded.actor,
                    recorded.note,

                    failed.error_message
                        AS error_message,

                    CASE
                        WHEN closed.resolution_event_id IS NOT NULL
                            THEN 'closed'
                        WHEN succeeded.resolution_event_id IS NOT NULL
                            THEN 'reentry_succeeded'
                        WHEN failed.resolution_event_id IS NOT NULL
                            THEN 'reentry_failed'
                        WHEN started.resolution_event_id IS NOT NULL
                            THEN 'reentry_started'
                        WHEN authorized.resolution_event_id IS NOT NULL
                            THEN 'reentry_authorized'
                        ELSE 'resolution_recorded'
                    END AS status

                FROM supplier_case_resolution_events AS recorded

                LEFT JOIN supplier_case_resolution_events AS authorized
                  ON authorized.case_id = recorded.case_id
                 AND authorized.event_type = 'reentry_authorized'

                LEFT JOIN supplier_case_resolution_events AS started
                  ON started.case_id = recorded.case_id
                 AND started.event_type = 'reentry_started'

                LEFT JOIN supplier_case_resolution_events AS succeeded
                  ON succeeded.case_id = recorded.case_id
                 AND succeeded.event_type = 'reentry_succeeded'

                LEFT JOIN supplier_case_resolution_events AS failed
                  ON failed.case_id = recorded.case_id
                 AND failed.event_type = 'reentry_failed'

                LEFT JOIN supplier_case_resolution_events AS closed
                  ON closed.case_id = recorded.case_id
                 AND closed.event_type = 'case_closed'

                WHERE recorded.event_type = 'resolution_recorded'

                ORDER BY recorded.resolution_event_id DESC
                LIMIT ?;
                """,
                (
                    limit,
                ),
            ).fetchall()

            return [
                CaseResolutionView(
                    **dict(row)
                )
                for row in rows
            ]

    def count_events(
        self,
    ) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_case_resolution_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplier_case_resolution_events;
                """
            ).fetchone()

            return int(
                row["count"]
            )
