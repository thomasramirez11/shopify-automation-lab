import json
import logging
from datetime import date, datetime

from database.connection import get_db_connection


logger = logging.getLogger(__name__)


class DailyReportRepository:
    """
    Persists immutable Shopify Automation Lab
    daily-report snapshots.

    Each save creates a new historical row.

    Existing reports are intentionally not updated,
    because a report should preserve what the system
    knew at the moment it was generated.
    """

    VALID_HEALTH_STATUSES = {
        "healthy",
        "attention",
        "critical",
    }

    def save_report(
        self,
        report: dict,
    ) -> int:
        """
        Persist one structured report snapshot.

        Returns the SQLite ID of the newly-created
        daily_reports row.
        """

        metadata = (
            self._extract_report_metadata(
                report
            )
        )

        report_json = (
            self._serialize_report(
                report
            )
        )

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO daily_reports (
                    business_date,
                    report_timezone,
                    generated_at_utc,
                    health_status,
                    report_json
                )
                VALUES (?, ?, ?, ?, ?);
                """,
                (
                    metadata[
                        "business_date"
                    ],
                    metadata[
                        "report_timezone"
                    ],
                    metadata[
                        "generated_at_utc"
                    ],
                    metadata[
                        "health_status"
                    ],
                    report_json,
                ),
            )

            report_id = (
                cursor.lastrowid
            )

        logger.info(
            "Saved daily report snapshot id=%s "
            "business_date='%s' health='%s'.",
            report_id,
            metadata["business_date"],
            metadata["health_status"],
        )

        return report_id

    def get_report_by_id(
        self,
        report_id: int,
    ):
        """
        Return one stored report snapshot by ID.

        Returns None when the report does not exist.
        """

        normalized_id = (
            self._validate_positive_integer(
                report_id,
                field_name="report_id",
            )
        )

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    business_date,
                    report_timezone,
                    generated_at_utc,
                    health_status,
                    report_json,
                    created_at
                FROM daily_reports
                WHERE id = ?;
                """,
                (
                    normalized_id,
                ),
            )

            row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_record(
            row
        )

    def get_latest_report(
        self,
    ):
        """
        Return the most recently generated
        report snapshot.

        Returns None if no report exists yet.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    business_date,
                    report_timezone,
                    generated_at_utc,
                    health_status,
                    report_json,
                    created_at
                FROM daily_reports
                ORDER BY
                    generated_at_utc DESC,
                    id DESC
                LIMIT 1;
                """
            )

            row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_record(
            row
        )

    def get_reports_for_date(
        self,
        business_date: str,
    ) -> list:
        """
        Return every report snapshot generated
        for one local business date.

        Newest snapshot appears first.
        """

        normalized_date = (
            self._validate_business_date(
                business_date
            )
        )

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    business_date,
                    report_timezone,
                    generated_at_utc,
                    health_status,
                    report_json,
                    created_at
                FROM daily_reports
                WHERE business_date = ?
                ORDER BY
                    generated_at_utc DESC,
                    id DESC;
                """,
                (
                    normalized_date,
                ),
            )

            rows = cursor.fetchall()

        return [
            self._row_to_record(
                row
            )
            for row in rows
        ]

    def get_recent_reports(
        self,
        *,
        limit: int = 10,
    ) -> list:
        """
        Return the most recent report snapshots.
        """

        normalized_limit = (
            self._validate_positive_integer(
                limit,
                field_name="limit",
            )
        )

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    business_date,
                    report_timezone,
                    generated_at_utc,
                    health_status,
                    report_json,
                    created_at
                FROM daily_reports
                ORDER BY
                    generated_at_utc DESC,
                    id DESC
                LIMIT ?;
                """,
                (
                    normalized_limit,
                ),
            )

            rows = cursor.fetchall()

        return [
            self._row_to_record(
                row
            )
            for row in rows
        ]

    def count_reports(
        self,
    ) -> int:
        """
        Return the total number of immutable
        daily-report snapshots.
        """

        with get_db_connection() as connection:
            cursor = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM daily_reports;
                """
            )

            row = cursor.fetchone()

        return row["count"]

    def _extract_report_metadata(
        self,
        report: dict,
    ) -> dict:
        """
        Validate the structured report and extract
        metadata required by daily_reports.

        Metadata is derived from the report itself
        so callers cannot accidentally save a report
        under a mismatched date, timezone, or status.
        """

        if not isinstance(
            report,
            dict,
        ):
            raise ValueError(
                "report must be a dictionary."
            )

        report_context = report.get(
            "report_context"
        )

        health = report.get(
            "health"
        )

        generated_at_utc = report.get(
            "generated_at_utc"
        )

        if not isinstance(
            report_context,
            dict,
        ):
            raise ValueError(
                "report must contain a "
                "report_context dictionary."
            )

        if not isinstance(
            health,
            dict,
        ):
            raise ValueError(
                "report must contain a "
                "health dictionary."
            )

        business_date = (
            self._validate_business_date(
                report_context.get(
                    "local_date"
                )
            )
        )

        report_timezone = (
            report_context.get(
                "timezone"
            )
        )

        if (
            not isinstance(
                report_timezone,
                str,
            )
            or not report_timezone.strip()
        ):
            raise ValueError(
                "report timezone is required."
            )

        normalized_generated_at = (
            self._validate_generated_at_utc(
                generated_at_utc
            )
        )

        health_status = (
            health.get(
                "status"
            )
        )

        if (
            not isinstance(
                health_status,
                str,
            )
            or health_status
            not in self.VALID_HEALTH_STATUSES
        ):
            raise ValueError(
                "health status must be one of: "
                "healthy, attention, critical."
            )

        return {
            "business_date":
                business_date,

            "report_timezone":
                report_timezone.strip(),

            "generated_at_utc":
                normalized_generated_at,

            "health_status":
                health_status,
        }

    def _serialize_report(
        self,
        report: dict,
    ) -> str:
        """
        Convert the complete structured report
        into deterministic JSON text.
        """

        try:
            return json.dumps(
                report,
                ensure_ascii=False,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "report contains data that "
                "cannot be serialized to JSON."
            ) from exc

    def _row_to_record(
        self,
        row,
    ) -> dict:
        """
        Convert one SQLite row into a repository
        record and deserialize report_json.
        """

        try:
            report_data = json.loads(
                row[
                    "report_json"
                ]
            )
        except (
            json.JSONDecodeError,
            TypeError,
        ) as exc:
            raise ValueError(
                "Stored report_json is invalid."
            ) from exc

        return {
            "id":
                row["id"],

            "business_date":
                row[
                    "business_date"
                ],

            "report_timezone":
                row[
                    "report_timezone"
                ],

            "generated_at_utc":
                row[
                    "generated_at_utc"
                ],

            "health_status":
                row[
                    "health_status"
                ],

            "report":
                report_data,

            "created_at":
                row[
                    "created_at"
                ],
        }

    def _validate_business_date(
        self,
        value,
    ) -> str:
        """
        Require an ISO calendar date:
        YYYY-MM-DD.
        """

        if (
            not isinstance(
                value,
                str,
            )
            or not value.strip()
        ):
            raise ValueError(
                "business_date is required."
            )

        normalized_value = (
            value.strip()
        )

        try:
            parsed = date.fromisoformat(
                normalized_value
            )
        except ValueError as exc:
            raise ValueError(
                "business_date must use "
                "YYYY-MM-DD format."
            ) from exc

        return parsed.isoformat()

    def _validate_generated_at_utc(
        self,
        value,
    ) -> str:
        """
        Require a timezone-aware ISO timestamp.

        ReportService already produces UTC, but this
        repository validates the persistence boundary.
        """

        if (
            not isinstance(
                value,
                str,
            )
            or not value.strip()
        ):
            raise ValueError(
                "generated_at_utc is required."
            )

        normalized_value = (
            value.strip()
        )

        try:
            parsed = datetime.fromisoformat(
                normalized_value.replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError as exc:
            raise ValueError(
                "generated_at_utc must be "
                "a valid ISO timestamp."
            ) from exc

        if parsed.tzinfo is None:
            raise ValueError(
                "generated_at_utc must include "
                "timezone information."
            )

        return normalized_value

    def _validate_positive_integer(
        self,
        value,
        *,
        field_name: str,
    ) -> int:
        """
        Validate positive integer IDs and limits.
        """

        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                int,
            )
            or value <= 0
        ):
            raise ValueError(
                f"{field_name} must be a "
                "positive integer."
            )
            

        return value
