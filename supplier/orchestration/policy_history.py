from __future__ import annotations

from database.connection import get_db_connection


class SQLiteSupplierPolicyHistoryReader:
    """
    Read-only policy context from the orchestration run ledger.
    """

    def __init__(
        self,
        *,
        connection_factory=get_db_connection,
    ) -> None:
        self._connection_factory = (
            connection_factory
        )

    def consecutive_human_attention_runs(
        self,
        supplier_code: str,
    ) -> int:
        with self._connection_factory() as connection:
            table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'supplier_orchestration_runs';
                """
            ).fetchone()

            if table is None:
                return 0

            rows = connection.execute(
                """
                SELECT posture
                FROM supplier_orchestration_runs
                WHERE supplier_code = ?
                ORDER BY run_id DESC;
                """,
                (
                    supplier_code,
                ),
            ).fetchall()

            count = 0

            for row in rows:
                if (
                    row["posture"]
                    != "human_attention"
                ):
                    break

                count += 1

            return count
