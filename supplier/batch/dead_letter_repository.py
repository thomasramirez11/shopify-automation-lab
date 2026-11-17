from __future__ import annotations

from database.connection import (
    get_db_connection,
)
from database.supplier_dead_letter_schema import (
    ensure_supplier_dead_letter_schema,
)
from supplier.batch.dead_letter_models import (
    DeadLetterAppendResult,
    DeadLetterAuditEvent,
    DeadLetterCandidate,
    DeadLetterCaseView,
    DeadLetterReason,
    StoredDeadLetterEvent,
)


class SupplierDeadLetterRepository:
    """
    Append-only dead-letter persistence plus terminal retry discovery.
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
            ensure_supplier_dead_letter_schema(
                connection
            )

    def discover_escalation_candidates(
        self,
    ) -> list[DeadLetterCandidate]:
        """
        Terminal retry facts become human-escalation candidates.

        RETRY_SUCCEEDED wins: a recovered item is never escalated.
        """

        with self._connection_factory() as connection:
            ensure_supplier_dead_letter_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    terminal.retry_id,
                    terminal.source_batch_id,
                    terminal.item_index,
                    terminal.operation_id,
                    terminal.shopify_variant_id,
                    terminal.shopify_sku,
                    terminal.requested_quantity,
                    terminal.event_type
                FROM supplier_batch_retry_events AS terminal
                WHERE terminal.event_type IN (
                    'retry_exhausted',
                    'retry_skipped'
                )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM supplier_batch_retry_events AS success
                      WHERE success.retry_id = terminal.retry_id
                        AND success.event_type = 'retry_succeeded'
                  )
                ORDER BY terminal.retry_event_id;
                """
            ).fetchall()

            candidates = []

            for row in rows:
                reason = (
                    DeadLetterReason.RETRY_EXHAUSTED
                    if row["event_type"]
                    == "retry_exhausted"
                    else (
                        DeadLetterReason
                        .NON_RETRYABLE_FAILURE
                    )
                )

                candidates.append(
                    DeadLetterCandidate(
                        source_retry_id=(
                            row["retry_id"]
                        ),
                        source_batch_id=(
                            row["source_batch_id"]
                        ),
                        item_index=(
                            row["item_index"]
                        ),
                        operation_id=(
                            row["operation_id"]
                        ),
                        shopify_variant_id=(
                            row["shopify_variant_id"]
                        ),
                        shopify_sku=(
                            row["shopify_sku"]
                        ),
                        requested_quantity=(
                            row["requested_quantity"]
                        ),
                        reason=reason,
                    )
                )

            return candidates

    def append(
        self,
        event: DeadLetterAuditEvent,
    ) -> DeadLetterAppendResult:
        with self._connection_factory() as connection:
            ensure_supplier_dead_letter_schema(
                connection
            )

            cursor = connection.execute(
                """
                INSERT INTO supplier_dead_letter_events (
                    case_id,
                    source_retry_id,
                    source_batch_id,
                    item_index,
                    operation_id,
                    shopify_variant_id,
                    shopify_sku,
                    requested_quantity,
                    reason_code,
                    event_type,
                    actor,
                    note
                )
                VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                ON CONFLICT(
                    case_id,
                    event_type
                )
                DO NOTHING;
                """,
                (
                    event.case_id,
                    event.source_retry_id,
                    event.source_batch_id,
                    event.item_index,
                    event.operation_id,
                    event.shopify_variant_id,
                    event.shopify_sku,
                    event.requested_quantity,
                    event.reason.value,
                    event.event_type.value,
                    event.actor,
                    event.note,
                ),
            )

            row = connection.execute(
                """
                SELECT dead_letter_event_id
                FROM supplier_dead_letter_events
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
                    "Dead-letter event could not be read after append."
                )

            return DeadLetterAppendResult(
                dead_letter_event_id=(
                    row["dead_letter_event_id"]
                ),
                created_new=(
                    cursor.rowcount == 1
                ),
            )

    def get_case_events(
        self,
        case_id: str,
    ) -> list[StoredDeadLetterEvent]:
        with self._connection_factory() as connection:
            ensure_supplier_dead_letter_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    dead_letter_event_id,
                    case_id,
                    source_retry_id,
                    source_batch_id,
                    item_index,
                    operation_id,
                    shopify_variant_id,
                    shopify_sku,
                    requested_quantity,
                    reason_code,
                    event_type,
                    actor,
                    note,
                    created_at
                FROM supplier_dead_letter_events
                WHERE case_id = ?
                ORDER BY dead_letter_event_id;
                """,
                (
                    case_id,
                ),
            ).fetchall()

            return [
                StoredDeadLetterEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def get_opened_event(
        self,
        case_id: str,
    ):
        events = self.get_case_events(
            case_id
        )

        for event in events:
            if (
                event.event_type
                == "case_opened"
            ):
                return event

        return None

    def get_acknowledged_event(
        self,
        case_id: str,
    ):
        events = self.get_case_events(
            case_id
        )

        for event in events:
            if (
                event.event_type
                == "case_acknowledged"
            ):
                return event

        return None

    def get_cases(
        self,
        *,
        limit: int = 20,
    ) -> list[DeadLetterCaseView]:
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
            ensure_supplier_dead_letter_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    opened.case_id,
                    opened.source_retry_id,
                    opened.source_batch_id,
                    opened.item_index,
                    opened.operation_id,
                    opened.shopify_variant_id,
                    opened.shopify_sku,
                    opened.requested_quantity,
                    opened.reason_code,

                    opened.created_at AS opened_at,

                    acknowledged.created_at
                        AS acknowledged_at,

                    acknowledged.actor
                        AS acknowledged_by,

                    acknowledged.note
                        AS acknowledgement_note

                FROM supplier_dead_letter_events AS opened

                LEFT JOIN supplier_dead_letter_events AS acknowledged
                  ON acknowledged.case_id = opened.case_id
                 AND acknowledged.event_type = 'case_acknowledged'

                WHERE opened.event_type = 'case_opened'

                ORDER BY opened.dead_letter_event_id DESC
                LIMIT ?;
                """,
                (
                    limit,
                ),
            ).fetchall()

            return [
                DeadLetterCaseView(
                    case_id=(
                        row["case_id"]
                    ),
                    source_retry_id=(
                        row["source_retry_id"]
                    ),
                    source_batch_id=(
                        row["source_batch_id"]
                    ),
                    item_index=(
                        row["item_index"]
                    ),
                    operation_id=(
                        row["operation_id"]
                    ),
                    shopify_variant_id=(
                        row["shopify_variant_id"]
                    ),
                    shopify_sku=(
                        row["shopify_sku"]
                    ),
                    requested_quantity=(
                        row["requested_quantity"]
                    ),
                    reason_code=(
                        row["reason_code"]
                    ),
                    status=(
                        "acknowledged"
                        if row["acknowledged_at"]
                        is not None
                        else "awaiting_human"
                    ),
                    opened_at=(
                        row["opened_at"]
                    ),
                    acknowledged_at=(
                        row["acknowledged_at"]
                    ),
                    acknowledged_by=(
                        row["acknowledged_by"]
                    ),
                    acknowledgement_note=(
                        row[
                            "acknowledgement_note"
                        ]
                    ),
                )
                for row in rows
            ]

    def count_events(
        self,
    ) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_dead_letter_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplier_dead_letter_events;
                """
            ).fetchone()

            return int(
                row["count"]
            )
