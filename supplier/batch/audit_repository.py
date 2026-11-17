from __future__ import annotations

from database.connection import (
    get_db_connection,
)
from database.supplier_batch_execution_schema import (
    ensure_supplier_batch_execution_schema,
)
from supplier.batch.audit_models import (
    AuditAppendResult,
    BatchExecutionAuditEvent,
    BatchItemAuditEvent,
    StoredBatchExecutionEvent,
    StoredBatchItemEvent,
)


class SupplierBatchExecutionAuditRepository:
    """
    Append-only persistence for batch parent/child audit events.
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
            ensure_supplier_batch_execution_schema(
                connection
            )

    def append_batch_event(
        self,
        event: BatchExecutionAuditEvent,
    ) -> AuditAppendResult:
        with self._connection_factory() as connection:
            ensure_supplier_batch_execution_schema(
                connection
            )

            cursor = connection.execute(
                """
                INSERT INTO supplier_batch_execution_events (
                    batch_id,
                    event_type,
                    source_plan_fingerprint,
                    manifest_fingerprint,
                    planned_mutations,
                    total_absolute_inventory_delta,
                    attempted_mutations,
                    applied_mutations,
                    failed_mutations
                )
                VALUES (
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?, ?
                )
                ON CONFLICT(
                    batch_id,
                    event_type
                )
                DO NOTHING;
                """,
                (
                    event.batch_id,
                    event.event_type.value,
                    event.source_plan_fingerprint,
                    event.manifest_fingerprint,
                    event.planned_mutations,
                    event.total_absolute_inventory_delta,
                    event.attempted_mutations,
                    event.applied_mutations,
                    event.failed_mutations,
                ),
            )

            row = connection.execute(
                """
                SELECT event_id
                FROM supplier_batch_execution_events
                WHERE batch_id = ?
                  AND event_type = ?;
                """,
                (
                    event.batch_id,
                    event.event_type.value,
                ),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "Batch audit event could not be read after append."
                )

            return AuditAppendResult(
                event_id=row["event_id"],
                created_new=(
                    cursor.rowcount == 1
                ),
            )

    def append_item_event(
        self,
        event: BatchItemAuditEvent,
    ) -> AuditAppendResult:
        with self._connection_factory() as connection:
            ensure_supplier_batch_execution_schema(
                connection
            )

            cursor = connection.execute(
                """
                INSERT INTO supplier_batch_item_events (
                    batch_id,
                    item_index,
                    operation_id,
                    event_type,
                    supplier_sku,
                    shopify_variant_id,
                    shopify_sku,
                    before_quantity,
                    requested_quantity,
                    inventory_delta,
                    error_message
                )
                VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?
                )
                ON CONFLICT(
                    batch_id,
                    item_index,
                    event_type
                )
                DO NOTHING;
                """,
                (
                    event.batch_id,
                    event.item_index,
                    event.operation_id,
                    event.event_type.value,
                    event.supplier_sku,
                    event.shopify_variant_id,
                    event.shopify_sku,
                    event.before_quantity,
                    event.requested_quantity,
                    event.inventory_delta,
                    event.error_message,
                ),
            )

            row = connection.execute(
                """
                SELECT item_event_id
                FROM supplier_batch_item_events
                WHERE batch_id = ?
                  AND item_index = ?
                  AND event_type = ?;
                """,
                (
                    event.batch_id,
                    event.item_index,
                    event.event_type.value,
                ),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "Batch item audit event could not be read after append."
                )

            return AuditAppendResult(
                event_id=row["item_event_id"],
                created_new=(
                    cursor.rowcount == 1
                ),
            )

    def get_terminal_batch_event(
        self,
        batch_id: str,
    ):
        with self._connection_factory() as connection:
            ensure_supplier_batch_execution_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT
                    event_id,
                    batch_id,
                    event_type,
                    source_plan_fingerprint,
                    manifest_fingerprint,
                    planned_mutations,
                    total_absolute_inventory_delta,
                    attempted_mutations,
                    applied_mutations,
                    failed_mutations,
                    created_at
                FROM supplier_batch_execution_events
                WHERE batch_id = ?
                  AND event_type IN (
                      'batch_completed',
                      'batch_partial_failure',
                      'batch_failed'
                  )
                ORDER BY event_id
                LIMIT 1;
                """,
                (
                    batch_id,
                ),
            ).fetchone()

            return (
                StoredBatchExecutionEvent(
                    **dict(row)
                )
                if row is not None
                else None
            )

    def get_item_outcome_event(
        self,
        *,
        batch_id: str,
        item_index: int,
    ):
        with self._connection_factory() as connection:
            ensure_supplier_batch_execution_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT
                    item_event_id,
                    batch_id,
                    item_index,
                    operation_id,
                    event_type,
                    supplier_sku,
                    shopify_variant_id,
                    shopify_sku,
                    before_quantity,
                    requested_quantity,
                    inventory_delta,
                    error_message,
                    created_at
                FROM supplier_batch_item_events
                WHERE batch_id = ?
                  AND item_index = ?
                  AND event_type IN (
                      'item_applied',
                      'item_failed'
                  )
                ORDER BY item_event_id
                LIMIT 1;
                """,
                (
                    batch_id,
                    item_index,
                ),
            ).fetchone()

            return (
                StoredBatchItemEvent(
                    **dict(row)
                )
                if row is not None
                else None
            )

    def get_batch_events(
        self,
        batch_id: str,
    ) -> list[StoredBatchExecutionEvent]:
        with self._connection_factory() as connection:
            ensure_supplier_batch_execution_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    event_id,
                    batch_id,
                    event_type,
                    source_plan_fingerprint,
                    manifest_fingerprint,
                    planned_mutations,
                    total_absolute_inventory_delta,
                    attempted_mutations,
                    applied_mutations,
                    failed_mutations,
                    created_at
                FROM supplier_batch_execution_events
                WHERE batch_id = ?
                ORDER BY event_id;
                """,
                (
                    batch_id,
                ),
            ).fetchall()

            return [
                StoredBatchExecutionEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def get_item_events(
        self,
        batch_id: str,
    ) -> list[StoredBatchItemEvent]:
        with self._connection_factory() as connection:
            ensure_supplier_batch_execution_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    item_event_id,
                    batch_id,
                    item_index,
                    operation_id,
                    event_type,
                    supplier_sku,
                    shopify_variant_id,
                    shopify_sku,
                    before_quantity,
                    requested_quantity,
                    inventory_delta,
                    error_message,
                    created_at
                FROM supplier_batch_item_events
                WHERE batch_id = ?
                ORDER BY
                    item_index,
                    item_event_id;
                """,
                (
                    batch_id,
                ),
            ).fetchall()

            return [
                StoredBatchItemEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def get_recent_batch_ids(
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
            ensure_supplier_batch_execution_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    batch_id,
                    MAX(event_id) AS newest_event_id
                FROM supplier_batch_execution_events
                GROUP BY batch_id
                ORDER BY newest_event_id DESC
                LIMIT ?;
                """,
                (
                    limit,
                ),
            ).fetchall()

            return [
                row["batch_id"]
                for row in rows
            ]

    def count_batch_events(
        self,
    ) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_batch_execution_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplier_batch_execution_events;
                """
            ).fetchone()

            return int(
                row["count"]
            )

    def count_item_events(
        self,
    ) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_batch_execution_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplier_batch_item_events;
                """
            ).fetchone()

            return int(
                row["count"]
            )
