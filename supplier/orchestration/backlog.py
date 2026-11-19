from __future__ import annotations

from database.connection import get_db_connection
from supplier.orchestration.models import SupplierOperationsBacklog


class SQLiteSupplierOperationsBacklogReader:
    """
    Read-only view over retry, DLQ and case-resolution state.

    Important:
    - does not create tables
    - does not mutate SQLite
    - missing subsystem tables are treated as empty
    """

    def __init__(
        self,
        *,
        connection_factory=get_db_connection,
    ) -> None:
        self._connection_factory = connection_factory

    def read(self) -> SupplierOperationsBacklog:
        with self._connection_factory() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table';
                    """
                ).fetchall()
            }

            queued_retry_attempts = 0
            if "supplier_batch_retry_events" in tables:
                queued_retry_attempts = (
                    self._queued_retry_attempts(
                        connection
                    )
                )

            dlq_awaiting = 0
            dlq_acknowledged = 0

            if "supplier_dead_letter_events" in tables:
                (
                    dlq_awaiting,
                    dlq_acknowledged,
                ) = self._dead_letter_counts(
                    connection,
                    has_resolution_table=(
                        "supplier_case_resolution_events"
                        in tables
                    ),
                )

            resolution_counts = {}

            if (
                "supplier_case_resolution_events"
                in tables
            ):
                resolution_counts = (
                    self._resolution_counts(
                        connection
                    )
                )

            return SupplierOperationsBacklog(
                queued_retry_attempts=(
                    queued_retry_attempts
                ),
                dead_letter_awaiting_human=(
                    dlq_awaiting
                ),
                dead_letter_acknowledged=(
                    dlq_acknowledged
                ),
                resolution_recorded=(
                    resolution_counts.get(
                        "resolution_recorded",
                        0,
                    )
                ),
                reentry_authorized=(
                    resolution_counts.get(
                        "reentry_authorized",
                        0,
                    )
                ),
                reentry_started=(
                    resolution_counts.get(
                        "reentry_started",
                        0,
                    )
                ),
                reentry_failed=(
                    resolution_counts.get(
                        "reentry_failed",
                        0,
                    )
                ),
                resolution_closed=(
                    resolution_counts.get(
                        "closed",
                        0,
                    )
                ),
            )

    def _queued_retry_attempts(
        self,
        connection,
    ) -> int:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM supplier_batch_retry_events AS queued

            WHERE queued.event_type = 'retry_queued'

              AND NOT EXISTS (
                  SELECT 1
                  FROM supplier_batch_retry_events AS started
                  WHERE started.retry_id = queued.retry_id
                    AND started.attempt_number = queued.attempt_number
                    AND started.event_type = 'retry_started'
              )

              AND NOT EXISTS (
                  SELECT 1
                  FROM supplier_batch_retry_events AS terminal
                  WHERE terminal.retry_id = queued.retry_id
                    AND terminal.event_type IN (
                        'retry_succeeded',
                        'retry_exhausted'
                    )
              );
            """
        ).fetchone()

        return int(row["count"])

    def _dead_letter_counts(
        self,
        connection,
        *,
        has_resolution_table: bool,
    ) -> tuple[int, int]:
        if has_resolution_table:
            rows = connection.execute(
                """
                SELECT
                    opened.case_id,

                    CASE
                        WHEN acknowledged.dead_letter_event_id
                            IS NOT NULL
                            THEN 'acknowledged'
                        ELSE 'awaiting_human'
                    END AS dlq_status

                FROM supplier_dead_letter_events AS opened

                LEFT JOIN supplier_dead_letter_events AS acknowledged
                  ON acknowledged.case_id = opened.case_id
                 AND acknowledged.event_type = 'case_acknowledged'

                WHERE opened.event_type = 'case_opened'

                  AND NOT EXISTS (
                      SELECT 1
                      FROM supplier_case_resolution_events AS closed
                      WHERE closed.case_id = opened.case_id
                        AND closed.event_type = 'case_closed'
                  );
                """
            ).fetchall()

        else:
            rows = connection.execute(
                """
                SELECT
                    opened.case_id,

                    CASE
                        WHEN acknowledged.dead_letter_event_id
                            IS NOT NULL
                            THEN 'acknowledged'
                        ELSE 'awaiting_human'
                    END AS dlq_status

                FROM supplier_dead_letter_events AS opened

                LEFT JOIN supplier_dead_letter_events AS acknowledged
                  ON acknowledged.case_id = opened.case_id
                 AND acknowledged.event_type = 'case_acknowledged'

                WHERE opened.event_type = 'case_opened';
                """
            ).fetchall()

        awaiting = sum(
            1
            for row in rows
            if row["dlq_status"] == "awaiting_human"
        )

        acknowledged = sum(
            1
            for row in rows
            if row["dlq_status"] == "acknowledged"
        )

        return (
            awaiting,
            acknowledged,
        )

    def _resolution_counts(
        self,
        connection,
    ) -> dict[str, int]:
        rows = connection.execute(
            """
            SELECT
                recorded.case_id,

                CASE
                    WHEN closed.resolution_event_id IS NOT NULL
                        THEN 'closed'
                    WHEN failed.resolution_event_id IS NOT NULL
                        THEN 'reentry_failed'
                    WHEN succeeded.resolution_event_id IS NOT NULL
                        THEN 'reentry_succeeded'
                    WHEN started.resolution_event_id IS NOT NULL
                        THEN 'reentry_started'
                    WHEN authorized.resolution_event_id IS NOT NULL
                        THEN 'reentry_authorized'
                    ELSE 'resolution_recorded'
                END AS state

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

            WHERE recorded.event_type = 'resolution_recorded';
            """
        ).fetchall()

        counts = {}

        for row in rows:
            state = row["state"]

            # A success should be immediately followed by CASE_CLOSED.
            # If an interrupted process exposes this intermediate state,
            # keep human attention on it.
            if state == "reentry_succeeded":
                state = "reentry_started"

            counts[state] = counts.get(
                state,
                0,
            ) + 1

        return counts
