from __future__ import annotations

from database.connection import (
    get_db_connection,
)
from database.supplier_batch_retry_schema import (
    ensure_supplier_batch_retry_schema,
)
from supplier.batch.retry_models import (
    FailedBatchItem,
    RetryAppendResult,
    RetryAuditEvent,
    StoredRetryEvent,
)


class SupplierBatchRetryRepository:
    """
    Append-only retry queue and recovery event repository.
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
            ensure_supplier_batch_retry_schema(
                connection
            )

    def discover_failed_items(
        self,
    ) -> list[FailedBatchItem]:
        """
        Read original batch ITEM_FAILED facts.

        Successful batch items never appear here.
        """

        with self._connection_factory() as connection:
            ensure_supplier_batch_retry_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    batch_id,
                    item_index,
                    operation_id,
                    shopify_variant_id,
                    shopify_sku,
                    before_quantity,
                    requested_quantity,
                    inventory_delta,
                    error_message
                FROM supplier_batch_item_events
                WHERE event_type = 'item_failed'
                ORDER BY item_event_id;
                """
            ).fetchall()

            return [
                FailedBatchItem(
                    source_batch_id=(
                        row["batch_id"]
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
                    before_quantity=(
                        row["before_quantity"]
                    ),
                    requested_quantity=(
                        row["requested_quantity"]
                    ),
                    inventory_delta=(
                        row["inventory_delta"]
                    ),
                    original_error_message=(
                        row["error_message"]
                        or ""
                    ),
                )
                for row in rows
            ]

    def append(
        self,
        event: RetryAuditEvent,
    ) -> RetryAppendResult:
        with self._connection_factory() as connection:
            ensure_supplier_batch_retry_schema(
                connection
            )

            cursor = connection.execute(
                """
                INSERT INTO supplier_batch_retry_events (
                    retry_id,
                    source_batch_id,
                    item_index,
                    operation_id,
                    shopify_variant_id,
                    shopify_sku,
                    before_quantity,
                    requested_quantity,
                    inventory_delta,
                    attempt_number,
                    event_type,
                    error_message
                )
                VALUES (
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?
                )
                ON CONFLICT(
                    retry_id,
                    attempt_number,
                    event_type
                )
                DO NOTHING;
                """,
                (
                    event.retry_id,
                    event.source_batch_id,
                    event.item_index,
                    event.operation_id,
                    event.shopify_variant_id,
                    event.shopify_sku,
                    event.before_quantity,
                    event.requested_quantity,
                    event.inventory_delta,
                    event.attempt_number,
                    event.event_type.value,
                    event.error_message,
                ),
            )

            row = connection.execute(
                """
                SELECT retry_event_id
                FROM supplier_batch_retry_events
                WHERE retry_id = ?
                  AND attempt_number = ?
                  AND event_type = ?;
                """,
                (
                    event.retry_id,
                    event.attempt_number,
                    event.event_type.value,
                ),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "Retry event could not be read after append."
                )

            return RetryAppendResult(
                retry_event_id=(
                    row["retry_event_id"]
                ),
                created_new=(
                    cursor.rowcount == 1
                ),
            )

    def count_attempts(
        self,
        retry_id: str,
    ) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_batch_retry_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(
                    DISTINCT attempt_number
                ) AS count
                FROM supplier_batch_retry_events
                WHERE retry_id = ?
                  AND event_type = 'retry_started';
                """,
                (
                    retry_id,
                ),
            ).fetchone()

            return int(
                row["count"]
            )

    def has_success(
        self,
        retry_id: str,
    ) -> bool:
        return self._has_event(
            retry_id=retry_id,
            event_type="retry_succeeded",
        )

    def has_exhausted(
        self,
        retry_id: str,
    ) -> bool:
        return self._has_event(
            retry_id=retry_id,
            event_type="retry_exhausted",
        )

    def _has_event(
        self,
        *,
        retry_id: str,
        event_type: str,
    ) -> bool:
        with self._connection_factory() as connection:
            ensure_supplier_batch_retry_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT retry_event_id
                FROM supplier_batch_retry_events
                WHERE retry_id = ?
                  AND event_type = ?
                LIMIT 1;
                """,
                (
                    retry_id,
                    event_type,
                ),
            ).fetchone()

            return row is not None

    def get_queued_attempts(
        self,
    ) -> list[StoredRetryEvent]:
        """
        Return queued attempts that have not started yet.
        """

        with self._connection_factory() as connection:
            ensure_supplier_batch_retry_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    q.retry_event_id,
                    q.retry_id,
                    q.source_batch_id,
                    q.item_index,
                    q.operation_id,
                    q.shopify_variant_id,
                    q.shopify_sku,
                    q.before_quantity,
                    q.requested_quantity,
                    q.inventory_delta,
                    q.attempt_number,
                    q.event_type,
                    q.error_message,
                    q.created_at
                FROM supplier_batch_retry_events AS q
                WHERE q.event_type = 'retry_queued'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM supplier_batch_retry_events AS s
                      WHERE s.retry_id = q.retry_id
                        AND s.attempt_number = q.attempt_number
                        AND s.event_type = 'retry_started'
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM supplier_batch_retry_events AS done
                      WHERE done.retry_id = q.retry_id
                        AND done.event_type IN (
                            'retry_succeeded',
                            'retry_exhausted'
                        )
                  )
                ORDER BY q.retry_event_id;
                """
            ).fetchall()

            return [
                StoredRetryEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def get_retry_events(
        self,
        retry_id: str,
    ) -> list[StoredRetryEvent]:
        with self._connection_factory() as connection:
            ensure_supplier_batch_retry_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    retry_event_id,
                    retry_id,
                    source_batch_id,
                    item_index,
                    operation_id,
                    shopify_variant_id,
                    shopify_sku,
                    before_quantity,
                    requested_quantity,
                    inventory_delta,
                    attempt_number,
                    event_type,
                    error_message,
                    created_at
                FROM supplier_batch_retry_events
                WHERE retry_id = ?
                ORDER BY retry_event_id;
                """,
                (
                    retry_id,
                ),
            ).fetchall()

            return [
                StoredRetryEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def get_recent_retry_ids(
        self,
        *,
        limit: int = 10,
    ) -> list[str]:
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
            ensure_supplier_batch_retry_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    retry_id,
                    MAX(retry_event_id) AS newest
                FROM supplier_batch_retry_events
                GROUP BY retry_id
                ORDER BY newest DESC
                LIMIT ?;
                """,
                (
                    limit,
                ),
            ).fetchall()

            return [
                row["retry_id"]
                for row in rows
            ]

    def count_events(
        self,
    ) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_batch_retry_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplier_batch_retry_events;
                """
            ).fetchone()

            return int(
                row["count"]
            )
