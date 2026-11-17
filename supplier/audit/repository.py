from __future__ import annotations

from database.connection import get_db_connection
from database.supplier_execution_schema import (
    ensure_supplier_execution_schema,
)
from supplier.audit.models import (
    AuditAppendResult,
    StoredSupplierExecutionAuditEvent,
    SupplierExecutionAuditEvent,
)


class SupplierExecutionAuditRepository:
    """
    Append-only repository for supplier execution events.

    Re-appending the same operation/event pair is idempotent.
    """

    def __init__(
        self,
        *,
        connection_factory=get_db_connection,
    ) -> None:
        self._connection_factory = connection_factory

    def ensure_schema(self) -> None:
        with self._connection_factory() as connection:
            ensure_supplier_execution_schema(connection)

    def append(
        self,
        event: SupplierExecutionAuditEvent,
    ) -> AuditAppendResult:
        with self._connection_factory() as connection:
            ensure_supplier_execution_schema(connection)

            cursor = connection.execute(
                """
                INSERT INTO supplier_execution_events (
                    operation_id,
                    event_type,
                    supplier_code,
                    supplier_sku,
                    shopify_variant_id,
                    shopify_sku,
                    inventory_item_id,
                    location_id,
                    before_quantity,
                    requested_quantity,
                    observed_after_quantity,
                    inventory_delta,
                    plan_fingerprint,
                    idempotency_key,
                    baseline_sync_run_id,
                    error_message
                )
                VALUES (
                    ?, ?,
                    ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                ON CONFLICT(
                    operation_id,
                    event_type
                )
                DO NOTHING;
                """,
                (
                    event.operation_id,
                    event.event_type.value,
                    event.supplier_code,
                    event.supplier_sku,
                    event.shopify_variant_id,
                    event.shopify_sku,
                    event.inventory_item_id,
                    event.location_id,
                    event.before_quantity,
                    event.requested_quantity,
                    event.observed_after_quantity,
                    event.inventory_delta,
                    event.plan_fingerprint,
                    event.idempotency_key,
                    event.baseline_sync_run_id,
                    event.error_message,
                ),
            )

            created_new = cursor.rowcount == 1

            row = connection.execute(
                """
                SELECT event_id
                FROM supplier_execution_events
                WHERE operation_id = ?
                  AND event_type = ?;
                """,
                (
                    event.operation_id,
                    event.event_type.value,
                ),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "Execution audit event could not be read after append."
                )

            return AuditAppendResult(
                event_id=row["event_id"],
                created_new=created_new,
            )

    def get_operation_events(
        self,
        operation_id: str,
    ) -> list[StoredSupplierExecutionAuditEvent]:
        with self._connection_factory() as connection:
            ensure_supplier_execution_schema(connection)

            rows = connection.execute(
                """
                SELECT
                    event_id,
                    operation_id,
                    event_type,
                    supplier_code,
                    supplier_sku,
                    shopify_variant_id,
                    shopify_sku,
                    inventory_item_id,
                    location_id,
                    before_quantity,
                    requested_quantity,
                    observed_after_quantity,
                    inventory_delta,
                    plan_fingerprint,
                    idempotency_key,
                    baseline_sync_run_id,
                    error_message,
                    created_at
                FROM supplier_execution_events
                WHERE operation_id = ?
                ORDER BY event_id;
                """,
                (
                    operation_id,
                ),
            ).fetchall()

            return [
                StoredSupplierExecutionAuditEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def get_recent(
        self,
        *,
        limit: int = 20,
    ) -> list[StoredSupplierExecutionAuditEvent]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
        ):
            raise ValueError(
                "limit must be a positive integer."
            )

        with self._connection_factory() as connection:
            ensure_supplier_execution_schema(connection)

            rows = connection.execute(
                """
                SELECT
                    event_id,
                    operation_id,
                    event_type,
                    supplier_code,
                    supplier_sku,
                    shopify_variant_id,
                    shopify_sku,
                    inventory_item_id,
                    location_id,
                    before_quantity,
                    requested_quantity,
                    observed_after_quantity,
                    inventory_delta,
                    plan_fingerprint,
                    idempotency_key,
                    baseline_sync_run_id,
                    error_message,
                    created_at
                FROM supplier_execution_events
                ORDER BY event_id DESC
                LIMIT ?;
                """,
                (
                    limit,
                ),
            ).fetchall()

            return [
                StoredSupplierExecutionAuditEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def latest_successful_sync_run_id(
        self,
    ) -> int:
        """
        Return the newest successful V1 sync run ID.

        A value of 0 means no successful V1 run exists yet.
        """

        with self._connection_factory() as connection:
            table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'sync_runs';
                """
            ).fetchone()

            if table is None:
                return 0

            row = connection.execute(
                """
                SELECT id
                FROM sync_runs
                WHERE status = 'success'
                ORDER BY id DESC
                LIMIT 1;
                """
            ).fetchone()

            if row is None:
                return 0

            return int(
                row["id"]
            )

    def get_started_event(
        self,
        operation_id: str,
    ):
        events = self.get_operation_events(
            operation_id
        )

        for event in events:
            if (
                event.event_type
                == "execution_started"
            ):
                return event

        return None

    def count_events(self) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_execution_schema(connection)

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplier_execution_events;
                """
            ).fetchone()

            return int(row["count"])
