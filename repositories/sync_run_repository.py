import logging

from database.connection import get_db_connection


logger = logging.getLogger(__name__)


class SyncRunRepository:
    """
    Handles database operations related to synchronization runs.
    """

    def start_run(self) -> int:
        """
        Create a new synchronization run with status 'running'.

        Returns the database ID of the newly created run.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO sync_runs (
                    status
                )
                VALUES (?);
                """,
                ("running",),
            )

            run_id = cursor.lastrowid

        logger.info(
            "Started synchronization run %s.",
            run_id,
        )

        return run_id

    def mark_success(
        self,
        run_id: int,
        products_seen: int,
        variants_seen: int,
    ) -> None:
        """
        Mark a synchronization run as successfully completed.
        """

        with get_db_connection() as connection:
            connection.execute(
                """
                UPDATE sync_runs

                SET
                    completed_at = CURRENT_TIMESTAMP,
                    status = ?,
                    products_seen = ?,
                    variants_seen = ?,
                    error_message = NULL

                WHERE id = ?;
                """,
                (
                    "success",
                    products_seen,
                    variants_seen,
                    run_id,
                ),
            )

        logger.info(
            "Synchronization run %s completed successfully.",
            run_id,
        )

    def mark_failed(
        self,
        run_id: int,
        error_message: str,
    ) -> None:
        """
        Mark a synchronization run as failed.
        """

        with get_db_connection() as connection:
            connection.execute(
                """
                UPDATE sync_runs

                SET
                    completed_at = CURRENT_TIMESTAMP,
                    status = ?,
                    error_message = ?

                WHERE id = ?;
                """,
                (
                    "failed",
                    error_message[:1000],
                    run_id,
                ),
            )

        logger.error(
            "Synchronization run %s failed.",
            run_id,
        )

    def get_run_by_id(
        self,
        run_id: int,
    ):
        """
        Return one synchronization run by ID.

        Returns None if the run does not exist.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    started_at,
                    completed_at,
                    status,
                    products_seen,
                    variants_seen,
                    error_message

                FROM sync_runs

                WHERE id = ?;
                """,
                (run_id,),
            )

            row = cursor.fetchone()

            if row is None:
                return None

            return dict(row)

    def get_recent_runs(
        self,
        limit: int = 5,
        
    ) -> list:
        """
        Return the most recent synchronization runs.
        """



        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    started_at,
                    completed_at,
                    status,
                    products_seen,
                    variants_seen,
                    error_message

                FROM sync_runs

                ORDER BY id DESC

                LIMIT ?;
                """,
                (limit,),
            )

            return [
                dict(row)
                for row in cursor.fetchall()
            ]
        