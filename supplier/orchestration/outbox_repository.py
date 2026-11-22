from __future__ import annotations

from database.connection import (
    get_db_connection,
)
from database.supplier_notification_outbox_schema import (
    ensure_supplier_notification_outbox_schema,
)
from supplier.orchestration.outbox_models import (
    NotificationOutboxEventType,
    NotificationOutboxJob,
    NotificationOutboxState,
    StoredNotificationOutboxEvent,
)


_EVENT_TO_STATE = {
    NotificationOutboxEventType.ENQUEUED.value:
        NotificationOutboxState.ENQUEUED,
    NotificationOutboxEventType.CLAIMED.value:
        NotificationOutboxState.CLAIMED,
    NotificationOutboxEventType.DELIVERED.value:
        NotificationOutboxState.DELIVERED,
    NotificationOutboxEventType.FAILED.value:
        NotificationOutboxState.FAILED,
    NotificationOutboxEventType.RETRY_QUEUED.value:
        NotificationOutboxState.RETRY_QUEUED,
    NotificationOutboxEventType.DEAD_LETTERED.value:
        NotificationOutboxState.DEAD_LETTERED,
}


class SupplierNotificationOutboxRepository:
    """
    Append-only durable notification queue.
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
            ensure_supplier_notification_outbox_schema(
                connection
            )

    def enqueue(
        self,
        message,
    ) -> tuple[
        StoredNotificationOutboxEvent,
        bool,
    ]:
        return self.append_event(
            message=message,
            event_type=(
                NotificationOutboxEventType
                .ENQUEUED.value
            ),
            attempt_number=0,
        )

    def append_event(
        self,
        *,
        message,
        event_type: str,
        attempt_number: int,
        worker_id=None,
        provider_name=None,
        provider_message_id=None,
        error_message=None,
    ) -> tuple[
        StoredNotificationOutboxEvent,
        bool,
    ]:
        with self._connection_factory() as connection:
            ensure_supplier_notification_outbox_schema(
                connection
            )

            cursor = connection.execute(
                """
                INSERT INTO supplier_notification_outbox_events (
                    delivery_id,
                    route_event_id,
                    incident_id,
                    supplier_code,
                    route,
                    channel,
                    event_type,
                    attempt_number,
                    idempotency_key,
                    worker_id,
                    provider_name,
                    provider_message_id,
                    error_message,
                    subject,
                    body
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT (
                    delivery_id,
                    event_type,
                    attempt_number
                )
                DO NOTHING;
                """,
                (
                    message.delivery_id,
                    message.route_event_id,
                    message.incident_id,
                    message.supplier_code,
                    message.route,
                    message.channel.value,
                    event_type,
                    attempt_number,
                    message.idempotency_key,
                    worker_id,
                    provider_name,
                    provider_message_id,
                    error_message,
                    message.subject,
                    message.body,
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM supplier_notification_outbox_events
                WHERE delivery_id = ?
                  AND event_type = ?
                  AND attempt_number = ?;
                """,
                (
                    message.delivery_id,
                    event_type,
                    attempt_number,
                ),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "Outbox event could not be read after append."
                )

            return (
                StoredNotificationOutboxEvent(
                    **dict(row)
                ),
                cursor.rowcount == 1,
            )

    def get_events(
        self,
        delivery_id: str,
    ) -> list[
        StoredNotificationOutboxEvent
    ]:
        with self._connection_factory() as connection:
            ensure_supplier_notification_outbox_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT *
                FROM supplier_notification_outbox_events
                WHERE delivery_id = ?
                ORDER BY outbox_event_id;
                """,
                (
                    delivery_id,
                ),
            ).fetchall()

            return [
                StoredNotificationOutboxEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def get_job(
        self,
        delivery_id: str,
    ) -> NotificationOutboxJob | None:
        events = self.get_events(
            delivery_id
        )

        if not events:
            return None

        return _job_from_latest_event(
            events[-1]
        )

    def get_jobs_by_state(
        self,
        *,
        supplier_code: str,
        states,
        limit: int = 100,
    ) -> list[
        NotificationOutboxJob
    ]:
        _validate_limit(
            limit
        )

        state_values = tuple(
            state.value
            if isinstance(
                state,
                NotificationOutboxState,
            )
            else str(state)
            for state in states
        )

        event_types = tuple(
            _state_to_event_type(
                state
            )
            for state in state_values
        )

        if not event_types:
            return []

        placeholders = ",".join(
            "?"
            for _ in event_types
        )

        with self._connection_factory() as connection:
            ensure_supplier_notification_outbox_schema(
                connection
            )

            rows = connection.execute(
                f"""
                SELECT latest.*
                FROM supplier_notification_outbox_events AS latest

                JOIN (
                    SELECT
                        delivery_id,
                        MAX(outbox_event_id) AS max_event_id
                    FROM supplier_notification_outbox_events
                    WHERE supplier_code = ?
                    GROUP BY delivery_id
                ) AS current
                  ON current.max_event_id = latest.outbox_event_id

                WHERE latest.event_type IN (
                    {placeholders}
                )

                ORDER BY latest.outbox_event_id
                LIMIT ?;
                """,
                (
                    supplier_code,
                    *event_types,
                    limit,
                ),
            ).fetchall()

            return [
                _job_from_latest_event(
                    StoredNotificationOutboxEvent(
                        **dict(row)
                    )
                )
                for row in rows
            ]

    def get_pending_jobs(
        self,
        *,
        supplier_code: str,
        limit: int = 100,
    ):
        return self.get_jobs_by_state(
            supplier_code=supplier_code,
            states=(
                NotificationOutboxState.ENQUEUED,
                NotificationOutboxState.CLAIMED,
                NotificationOutboxState.RETRY_QUEUED,
            ),
            limit=limit,
        )

    def get_failed_jobs(
        self,
        *,
        supplier_code: str,
        limit: int = 100,
    ):
        return self.get_jobs_by_state(
            supplier_code=supplier_code,
            states=(
                NotificationOutboxState.FAILED,
            ),
            limit=limit,
        )

    def get_recent_events(
        self,
        *,
        supplier_code: str,
        limit: int = 100,
    ):
        _validate_limit(
            limit
        )

        with self._connection_factory() as connection:
            ensure_supplier_notification_outbox_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT *
                FROM supplier_notification_outbox_events
                WHERE supplier_code = ?
                ORDER BY outbox_event_id DESC
                LIMIT ?;
                """,
                (
                    supplier_code,
                    limit,
                ),
            ).fetchall()

            return [
                StoredNotificationOutboxEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def count_jobs(
        self,
        supplier_code: str,
    ) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_notification_outbox_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(
                    DISTINCT delivery_id
                ) AS count
                FROM supplier_notification_outbox_events
                WHERE supplier_code = ?;
                """,
                (
                    supplier_code,
                ),
            ).fetchone()

            return int(
                row["count"]
            )

    def count_state(
        self,
        *,
        supplier_code: str,
        state: NotificationOutboxState,
    ) -> int:
        return len(
            self.get_jobs_by_state(
                supplier_code=supplier_code,
                states=(state,),
                limit=10000,
            )
        )


def _job_from_latest_event(
    event: StoredNotificationOutboxEvent,
) -> NotificationOutboxJob:
    return NotificationOutboxJob(
        delivery_id=(
            event.delivery_id
        ),
        state=(
            _EVENT_TO_STATE[
                event.event_type
            ]
        ),
        attempt_number=(
            event.attempt_number
        ),
        message=(
            event.to_message()
        ),
        latest_event_id=(
            event.outbox_event_id
        ),
        latest_created_at=(
            event.created_at
        ),
        error_message=(
            event.error_message
        ),
    )


def _state_to_event_type(
    state: str,
) -> str:
    lookup = {
        NotificationOutboxState.ENQUEUED.value:
            NotificationOutboxEventType.ENQUEUED.value,
        NotificationOutboxState.CLAIMED.value:
            NotificationOutboxEventType.CLAIMED.value,
        NotificationOutboxState.DELIVERED.value:
            NotificationOutboxEventType.DELIVERED.value,
        NotificationOutboxState.FAILED.value:
            NotificationOutboxEventType.FAILED.value,
        NotificationOutboxState.RETRY_QUEUED.value:
            NotificationOutboxEventType.RETRY_QUEUED.value,
        NotificationOutboxState.DEAD_LETTERED.value:
            NotificationOutboxEventType.DEAD_LETTERED.value,
    }

    if state not in lookup:
        raise ValueError(
            f"Unsupported outbox state: {state!r}"
        )

    return lookup[state]


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
