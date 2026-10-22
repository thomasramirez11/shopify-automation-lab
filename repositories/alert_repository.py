import logging

from database.connection import get_db_connection


logger = logging.getLogger(__name__)


class AlertRepository:
    """
    Handles persistent alert lifecycle management.

    Alerts can be:
        - created
        - seen repeatedly without duplication
        - resolved
        - created again later as new history
    """

    VALID_ALERT_TYPES = {
        "new_order",
        "missing_cost",
        "low_inventory",
        "sync_failure",
    }

    VALID_SEVERITIES = {
        "info",
        "warning",
        "error",
        "critical",
    }

    def create_or_touch_alert(
        self,
        *,
        alert_type: str,
        severity: str,
        dedupe_key: str,
        title: str,
        message: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> dict:
        """
        Create a new open alert or update an existing
        open alert with the same dedupe key.

        Existing open alerts:
            - remain one database row
            - occurrence_count increases
            - last_seen_at is refreshed

        Returns the current alert row.
        """

        normalized_type = (
            alert_type.strip().lower()
        )

        normalized_severity = (
            severity.strip().lower()
        )

        normalized_dedupe_key = (
            dedupe_key.strip()
        )

        normalized_title = (
            title.strip()
        )

        normalized_message = (
            message.strip()
        )

        self._validate_alert(
            alert_type=normalized_type,
            severity=normalized_severity,
            dedupe_key=normalized_dedupe_key,
            title=normalized_title,
            message=normalized_message,
        )

        with get_db_connection() as connection:
            existing_alert = (
                self._get_open_alert_by_dedupe_key(
                    connection=connection,
                    dedupe_key=(
                        normalized_dedupe_key
                    ),
                )
            )

            if existing_alert is not None:
                connection.execute(
                    """
                    UPDATE alerts
                    SET
                        severity = ?,
                        title = ?,
                        message = ?,
                        entity_type = ?,
                        entity_id = ?,
                        occurrence_count =
                            occurrence_count + 1,
                        last_seen_at =
                            CURRENT_TIMESTAMP
                    WHERE id = ?;
                    """,
                    (
                        normalized_severity,
                        normalized_title,
                        normalized_message,
                        entity_type,
                        entity_id,
                        existing_alert["id"],
                    ),
                )

                alert_id = existing_alert["id"]

                logger.info(
                    "Updated existing alert id=%s "
                    "dedupe_key='%s'.",
                    alert_id,
                    normalized_dedupe_key,
                )

            else:
                cursor = connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_type,
                        severity,
                        status,
                        dedupe_key,
                        title,
                        message,
                        entity_type,
                        entity_id
                    )
                    VALUES (
                        ?,
                        ?,
                        'open',
                        ?,
                        ?,
                        ?,
                        ?,
                        ?
                    );
                    """,
                    (
                        normalized_type,
                        normalized_severity,
                        normalized_dedupe_key,
                        normalized_title,
                        normalized_message,
                        entity_type,
                        entity_id,
                    ),
                )

                alert_id = cursor.lastrowid

                logger.info(
                    "Created alert id=%s "
                    "type='%s' dedupe_key='%s'.",
                    alert_id,
                    normalized_type,
                    normalized_dedupe_key,
                )

            return self._get_alert_by_id(
                connection=connection,
                alert_id=alert_id,
            )

    def resolve_alert(
        self,
        dedupe_key: str,
    ) -> bool:
        """
        Resolve the currently open alert
        matching one dedupe key.

        Returns:
            True if an open alert was resolved.
            False if no open alert existed.
        """

        normalized_dedupe_key = (
            dedupe_key.strip()
        )

        if not normalized_dedupe_key:
            raise ValueError(
                "dedupe_key is required."
            )

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE alerts
                SET
                    status = 'resolved',
                    resolved_at = CURRENT_TIMESTAMP,
                    last_seen_at = CURRENT_TIMESTAMP
                WHERE dedupe_key = ?
                  AND status = 'open';
                """,
                (
                    normalized_dedupe_key,
                ),
            )

            resolved = cursor.rowcount > 0

        if resolved:
            logger.info(
                "Resolved alert dedupe_key='%s'.",
                normalized_dedupe_key,
            )

        return resolved

    def get_alert_by_id(
        self,
        alert_id: int,
    ):
        """
        Return one alert by database ID.
        """

        with get_db_connection() as connection:
            return self._get_alert_by_id(
                connection=connection,
                alert_id=alert_id,
            )

    def get_open_alert_by_dedupe_key(
        self,
        dedupe_key: str,
    ):
        """
        Return the currently open alert for
        one dedupe key.

        Returns None if no matching open alert exists.
        """

        with get_db_connection() as connection:
            return (
                self._get_open_alert_by_dedupe_key(
                    connection=connection,
                    dedupe_key=dedupe_key,
                )
            )

    def get_open_alerts(
        self,
    ) -> list:
        """
        Return all currently open alerts,
        oldest first.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    alert_type,
                    severity,
                    status,
                    dedupe_key,
                    title,
                    message,
                    entity_type,
                    entity_id,
                    occurrence_count,
                    created_at,
                    last_seen_at,
                    resolved_at
                FROM alerts
                WHERE status = 'open'
                ORDER BY created_at ASC,
                         id ASC;
                """
            )

            return [
                dict(row)
                for row in cursor.fetchall()
            ]

    def get_recent_alerts(
        self,
        limit: int = 10,
    ) -> list:
        """
        Return recent alert history,
        including resolved alerts.
        """

        if limit <= 0:
            raise ValueError(
                "limit must be greater than zero."
            )

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    alert_type,
                    severity,
                    status,
                    dedupe_key,
                    title,
                    message,
                    entity_type,
                    entity_id,
                    occurrence_count,
                    created_at,
                    last_seen_at,
                    resolved_at
                FROM alerts
                ORDER BY id DESC
                LIMIT ?;
                """,
                (limit,),
            )

            return [
                dict(row)
                for row in cursor.fetchall()
            ]

    def count_open_alerts(
        self,
    ) -> int:
        """
        Return the number of currently open alerts.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM alerts
                WHERE status = 'open';
                """
            )

            row = cursor.fetchone()

            return row["count"]

    def count_all_alerts(
        self,
    ) -> int:
        """
        Return the total alert-history row count.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM alerts;
                """
            )

            row = cursor.fetchone()

            return row["count"]

    def _get_open_alert_by_dedupe_key(
        self,
        *,
        connection,
        dedupe_key: str,
    ):
        """
        Internal lookup using an existing transaction.
        """

        cursor = connection.execute(
            """
            SELECT
                id,
                alert_type,
                severity,
                status,
                dedupe_key,
                title,
                message,
                entity_type,
                entity_id,
                occurrence_count,
                created_at,
                last_seen_at,
                resolved_at
            FROM alerts
            WHERE dedupe_key = ?
              AND status = 'open'
            LIMIT 1;
            """,
            (dedupe_key,),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return dict(row)

    def _get_alert_by_id(
        self,
        *,
        connection,
        alert_id: int,
    ):
        """
        Internal lookup by database alert ID.
        """

        cursor = connection.execute(
            """
            SELECT
                id,
                alert_type,
                severity,
                status,
                dedupe_key,
                title,
                message,
                entity_type,
                entity_id,
                occurrence_count,
                created_at,
                last_seen_at,
                resolved_at
            FROM alerts
            WHERE id = ?;
            """,
            (alert_id,),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return dict(row)

    def _validate_alert(
        self,
        *,
        alert_type: str,
        severity: str,
        dedupe_key: str,
        title: str,
        message: str,
    ) -> None:
        """
        Validate alert data before persistence.
        """

        if alert_type not in (
            self.VALID_ALERT_TYPES
        ):
            raise ValueError(
                "Unsupported alert_type."
            )

        if severity not in (
            self.VALID_SEVERITIES
        ):
            raise ValueError(
                "Unsupported severity."
            )

        if not dedupe_key:
            raise ValueError(
                "dedupe_key is required."
            )

        if not title:
            raise ValueError(
                "title is required."
            )

        if not message:
            raise ValueError(
                "message is required."
            )