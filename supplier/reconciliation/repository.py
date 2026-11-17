from __future__ import annotations

from database.connection import get_db_connection
from database.supplier_reconciliation_schema import (
    ensure_supplier_reconciliation_schema,
)
from supplier.reconciliation.models import (
    ReconciliationAppendResult,
    ReconciliationObservation,
    StoredReconciliationEvent,
    VerifiedExecutionCandidate,
)


class SupplierExecutionReconciliationRepository:
    """
    Read V2 verified executions and V1 observation state, then append immutable
    reconciliation facts.
    """

    def __init__(
        self,
        *,
        connection_factory=get_db_connection,
    ) -> None:
        self._connection_factory = (
            connection_factory
        )

    def ensure_schema(self) -> None:
        with self._connection_factory() as connection:
            ensure_supplier_reconciliation_schema(
                connection
            )

    def get_verified_execution_candidates(
        self,
    ) -> list[VerifiedExecutionCandidate]:
        with self._connection_factory() as connection:
            ensure_supplier_reconciliation_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    event_id,
                    operation_id,
                    shopify_variant_id,
                    shopify_sku,
                    observed_after_quantity,
                    baseline_sync_run_id,
                    created_at
                FROM supplier_execution_events
                WHERE event_type = 'execution_verified'
                ORDER BY event_id;
                """
            ).fetchall()

            return [
                VerifiedExecutionCandidate(
                    verified_event_id=(
                        row["event_id"]
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
                    expected_quantity=(
                        row[
                            "observed_after_quantity"
                        ]
                    ),
                    baseline_sync_run_id=(
                        row[
                            "baseline_sync_run_id"
                        ]
                    ),
                    verified_at=(
                        row["created_at"]
                    ),
                )
                for row in rows
            ]

    def has_match(
        self,
        operation_id: str,
    ) -> bool:
        with self._connection_factory() as connection:
            ensure_supplier_reconciliation_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT reconciliation_id
                FROM supplier_execution_reconciliations
                WHERE operation_id = ?
                  AND status = 'match'
                LIMIT 1;
                """,
                (
                    operation_id,
                ),
            ).fetchone()

            return row is not None

    def latest_successful_sync_after(
        self,
        baseline_sync_run_id: int,
    ):
        with self._connection_factory() as connection:
            ensure_supplier_reconciliation_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT
                    id,
                    started_at,
                    completed_at
                FROM sync_runs
                WHERE status = 'success'
                  AND completed_at IS NOT NULL
                  AND id > ?
                ORDER BY id DESC
                LIMIT 1;
                """,
                (
                    baseline_sync_run_id,
                ),
            ).fetchone()

            return (
                dict(row)
                if row is not None
                else None
            )

    def get_variant_inventory(
        self,
        shopify_variant_id: str,
    ):
        with self._connection_factory() as connection:
            ensure_supplier_reconciliation_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT
                    shopify_variant_id,
                    sku,
                    inventory_quantity,
                    synced_at
                FROM variants
                WHERE shopify_variant_id = ?;
                """,
                (
                    shopify_variant_id,
                ),
            ).fetchone()

            return (
                dict(row)
                if row is not None
                else None
            )

    def append(
        self,
        observation: ReconciliationObservation,
    ) -> ReconciliationAppendResult:
        with self._connection_factory() as connection:
            ensure_supplier_reconciliation_schema(
                connection
            )

            cursor = connection.execute(
                """
                INSERT INTO supplier_execution_reconciliations (
                    operation_id,
                    verified_event_id,
                    sync_run_id,

                    shopify_variant_id,
                    shopify_sku,

                    expected_quantity,
                    observed_sqlite_quantity,

                    status
                )
                VALUES (
                    ?, ?, ?,
                    ?, ?,
                    ?, ?,
                    ?
                )
                ON CONFLICT(
                    operation_id,
                    sync_run_id
                )
                DO NOTHING;
                """,
                (
                    observation.operation_id,
                    observation.verified_event_id,
                    observation.sync_run_id,
                    observation.shopify_variant_id,
                    observation.shopify_sku,
                    observation.expected_quantity,
                    observation.observed_sqlite_quantity,
                    observation.status.value,
                ),
            )

            created_new = (
                cursor.rowcount == 1
            )

            row = connection.execute(
                """
                SELECT reconciliation_id
                FROM supplier_execution_reconciliations
                WHERE operation_id = ?
                  AND sync_run_id = ?;
                """,
                (
                    observation.operation_id,
                    observation.sync_run_id,
                ),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "Reconciliation event could not be read after append."
                )

            return ReconciliationAppendResult(
                reconciliation_id=(
                    row["reconciliation_id"]
                ),
                created_new=(
                    created_new
                ),
            )

    def get_recent(
        self,
        *,
        limit: int = 20,
    ) -> list[StoredReconciliationEvent]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
        ):
            raise ValueError(
                "limit must be a positive integer."
            )

        with self._connection_factory() as connection:
            ensure_supplier_reconciliation_schema(
                connection
            )

            rows = connection.execute(
                """
                SELECT
                    reconciliation_id,
                    operation_id,
                    verified_event_id,
                    sync_run_id,
                    shopify_variant_id,
                    shopify_sku,
                    expected_quantity,
                    observed_sqlite_quantity,
                    status,
                    created_at
                FROM supplier_execution_reconciliations
                ORDER BY reconciliation_id DESC
                LIMIT ?;
                """,
                (
                    limit,
                ),
            ).fetchall()

            return [
                StoredReconciliationEvent(
                    **dict(row)
                )
                for row in rows
            ]

    def count_events(self) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_reconciliation_schema(
                connection
            )

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplier_execution_reconciliations;
                """
            ).fetchone()

            return int(
                row["count"]
            )
