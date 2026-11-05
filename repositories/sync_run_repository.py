import logging

from database.connection import get_db_connection


logger = logging.getLogger(__name__)


class SyncRunStateError(RuntimeError):
    """
    Raised when an invalid synchronization-run state
    transition is attempted.
    """


class SyncRunRepository:
    """
    Handles database operations related to synchronization runs.

    Synchronization runs follow a small lifecycle:

        running -> success
        running -> failed

    Once a run reaches success or failed, it is treated as
    immutable audit history and cannot transition again.
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
        Mark a running synchronization run as successful.

        A completed run cannot be changed again because
        synchronization history is audit data.
        """

        self._validate_run_id(run_id)

        self._validate_non_negative_count(
            products_seen,
            field_name="products_seen",
        )

        self._validate_non_negative_count(
            variants_seen,
            field_name="variants_seen",
        )

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE sync_runs

                SET
                    completed_at = CURRENT_TIMESTAMP,
                    status = ?,
                    products_seen = ?,
                    variants_seen = ?,
                    error_message = NULL

                WHERE id = ?
                  AND status = 'running';
                """,
                (
                    "success",
                    products_seen,
                    variants_seen,
                    run_id,
                ),
            )

            if cursor.rowcount == 0:
                self._raise_invalid_transition(
                    connection,
                    run_id=run_id,
                    target_status="success",
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
        Mark a running synchronization run as failed.

        A completed run cannot be changed again because
        synchronization history is audit data.
        """

        self._validate_run_id(run_id)

        normalized_error = self._normalize_error_message(
            error_message
        )

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE sync_runs

                SET
                    completed_at = CURRENT_TIMESTAMP,
                    status = ?,
                    error_message = ?

                WHERE id = ?
                  AND status = 'running';
                """,
                (
                    "failed",
                    normalized_error[:1000],
                    run_id,
                ),
            )

            if cursor.rowcount == 0:
                self._raise_invalid_transition(
                    connection,
                    run_id=run_id,
                    target_status="failed",
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

        self._validate_run_id(run_id)

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

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
        ):
            raise ValueError(
                "limit must be an integer."
            )

        if limit < 0:
            raise ValueError(
                "limit cannot be negative."
            )

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

    def _raise_invalid_transition(
        self,
        connection,
        *,
        run_id: int,
        target_status: str,
    ) -> None:
        """
        Raise a clear error when a run cannot transition.

        Distinguishes a missing run from a run that already
        reached a terminal state.
        """

        row = connection.execute(
            """
            SELECT status
            FROM sync_runs
            WHERE id = ?;
            """,
            (run_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                f"Synchronization run {run_id} does not exist."
            )

        current_status = row["status"]

        raise SyncRunStateError(
            "Synchronization run "
            f"{run_id} cannot transition from "
            f"{current_status!r} to "
            f"{target_status!r}."
        )

    def _validate_run_id(
        self,
        run_id: int,
    ) -> None:
        """
        Validate one synchronization-run database ID.
        """

        if (
            isinstance(run_id, bool)
            or not isinstance(run_id, int)
            or run_id <= 0
        ):
            raise ValueError(
                "run_id must be a positive integer."
            )

    def _validate_non_negative_count(
        self,
        value: int,
        *,
        field_name: str,
    ) -> None:
        """
        Validate one synchronization count.
        """

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
        ):
            raise ValueError(
                f"{field_name} must be an integer."
            )

        if value < 0:
            raise ValueError(
                f"{field_name} cannot be negative."
            )

    def _normalize_error_message(
        self,
        error_message: str,
    ) -> str:
        """
        Validate and normalize one synchronization error.
        """

        if not isinstance(
            error_message,
            str,
        ):
            raise ValueError(
                "error_message must be a string."
            )

        normalized_error = error_message.strip()

        if not normalized_error:
            raise ValueError(
                "error_message is required."
            )

        return normalized_error
