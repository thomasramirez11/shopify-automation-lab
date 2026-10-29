import logging
from datetime import datetime

from repositories.daily_report_repository import (
    DailyReportRepository,
)
from services.report_formatter import (
    TerminalReportFormatter,
)
from services.report_service import (
    ReportService,
)


logger = logging.getLogger(__name__)


class DailyReportService:
    """
    Coordinate daily-report generation, formatting,
    and immutable persistence.

    ReportService:
        Builds trusted structured business data.

    TerminalReportFormatter:
        Converts that data into human-readable text.

    DailyReportRepository:
        Persists the structured report snapshot.
    """

    def __init__(
        self,
        *,
        report_service: ReportService,
        report_formatter: TerminalReportFormatter,
        daily_report_repository: DailyReportRepository,
    ):
        self.report_service = (
            report_service
        )

        self.report_formatter = (
            report_formatter
        )

        self.daily_report_repository = (
            daily_report_repository
        )

    def generate_and_save_report(
        self,
        *,
        now_utc: datetime | None = None,
    ) -> dict:
        """
        Generate one report, format it for terminal
        display, persist the structured snapshot,
        and return all three results.

        The structured report is saved before being
        returned so a successful call guarantees that
        the historical snapshot exists in SQLite.
        """

        report = (
            self.report_service
            .generate_store_health_snapshot(
                now_utc=now_utc
            )
        )

        formatted_report = (
            self.report_formatter
            .format_daily_report(
                report
            )
        )

        report_id = (
            self.daily_report_repository
            .save_report(
                report
            )
        )

        logger.info(
            "Generated and saved daily report "
            "id=%s business_date='%s' health='%s'.",
            report_id,
            report[
                "report_context"
            ][
                "local_date"
            ],
            report[
                "health"
            ][
                "status"
            ],
        )

        return {
            "report_id":
                report_id,

            "report":
                report,

            "formatted_report":
                formatted_report,
        }
