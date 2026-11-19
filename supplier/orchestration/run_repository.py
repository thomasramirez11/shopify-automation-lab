from __future__ import annotations

from database.connection import get_db_connection
from database.supplier_orchestration_schema import ensure_supplier_orchestration_schema
from supplier.orchestration.run_models import StoredOrchestrationRun


class SupplierOrchestrationRunRepository:
    """Append-only persistence for control-plane observations."""

    def __init__(self, *, connection_factory=get_db_connection) -> None:
        self._connection_factory = connection_factory

    def ensure_schema(self) -> None:
        with self._connection_factory() as connection:
            ensure_supplier_orchestration_schema(connection)

    def append(self, *, snapshot, previous_run: StoredOrchestrationRun | None) -> StoredOrchestrationRun:
        posture_changed = previous_run is not None and previous_run.posture != snapshot.posture.value
        next_action_changed = previous_run is not None and previous_run.next_action != snapshot.next_action.value
        with self._connection_factory() as connection:
            ensure_supplier_orchestration_schema(connection)
            cursor = connection.execute(
                """
                INSERT INTO supplier_orchestration_runs (
                    supplier_code, orchestration_fingerprint, manifest_fingerprint, posture, next_action,
                    planned_mutations, review_items, blocked_items, no_action_items,
                    queued_retry_attempts, dead_letter_awaiting_human, dead_letter_acknowledged,
                    resolution_recorded, reentry_authorized, reentry_started, reentry_failed, resolution_closed,
                    previous_run_id, previous_posture, posture_changed, next_action_changed
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
                """,
                (
                    snapshot.supplier_code, snapshot.orchestration_fingerprint,
                    snapshot.manifest.manifest_fingerprint, snapshot.posture.value, snapshot.next_action.value,
                    snapshot.plan.planned_mutations, snapshot.plan.review_items, snapshot.plan.blocked_items,
                    snapshot.plan.no_action_items, snapshot.backlog.queued_retry_attempts,
                    snapshot.backlog.dead_letter_awaiting_human, snapshot.backlog.dead_letter_acknowledged,
                    snapshot.backlog.resolution_recorded, snapshot.backlog.reentry_authorized,
                    snapshot.backlog.reentry_started, snapshot.backlog.reentry_failed,
                    snapshot.backlog.resolution_closed,
                    previous_run.run_id if previous_run else None,
                    previous_run.posture if previous_run else None,
                    int(posture_changed), int(next_action_changed),
                ),
            )
            row = connection.execute(
                'SELECT * FROM supplier_orchestration_runs WHERE run_id = ?;',
                (cursor.lastrowid,),
            ).fetchone()
            return StoredOrchestrationRun(**dict(row))

    def get_latest(self, supplier_code: str) -> StoredOrchestrationRun | None:
        with self._connection_factory() as connection:
            ensure_supplier_orchestration_schema(connection)
            row = connection.execute(
                """SELECT * FROM supplier_orchestration_runs
                   WHERE supplier_code = ? ORDER BY run_id DESC LIMIT 1;""",
                (supplier_code,),
            ).fetchone()
            return StoredOrchestrationRun(**dict(row)) if row is not None else None

    def get_recent(self, *, supplier_code: str, limit: int = 20) -> list[StoredOrchestrationRun]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError('limit must be a positive integer.')
        with self._connection_factory() as connection:
            ensure_supplier_orchestration_schema(connection)
            rows = connection.execute(
                """SELECT * FROM supplier_orchestration_runs
                   WHERE supplier_code = ? ORDER BY run_id DESC LIMIT ?;""",
                (supplier_code, limit),
            ).fetchall()
            return [StoredOrchestrationRun(**dict(row)) for row in rows]

    def count_runs(self, supplier_code: str) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_orchestration_schema(connection)
            row = connection.execute(
                'SELECT COUNT(*) AS count FROM supplier_orchestration_runs WHERE supplier_code = ?;',
                (supplier_code,),
            ).fetchone()
            return int(row['count'])
