from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from application.bootstrap import (
    build_daily_report_service,
)
from application.presentation_ports import ReportingPresenter


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportingWorkflowResult:
    """
    Outcome of the post-synchronization daily reporting workflow.

    Reporting is intentionally isolated from synchronization status.
    A failed report must not retroactively fail an already-successful
    Shopify synchronization run.
    """

    success: bool
    report_id: int | None
    health_status: str | None
    error_type: str | None
    error_message: str | None


def run_reporting_workflow(
    *,
    sync_run_id: int,
    product_repository: Any,
    order_repository: Any,
    alert_repository: Any,
    sync_run_repository: Any,
    profit_snapshot_repository: Any,
    presenter: ReportingPresenter,
    daily_report_service_builder: Callable[..., Any] | None = None,
) -> ReportingWorkflowResult:
    """
    Generate, persist, and display the daily report.

    This workflow runs only after synchronization has already been
    marked successful. All reporting failures are isolated here and
    returned as data instead of escaping into the synchronization
    failure boundary.
    """

    if daily_report_service_builder is None:
        daily_report_service_builder = (
            build_daily_report_service
        )

    try:
        daily_report_service = (
            daily_report_service_builder(
                product_repository=(
                    product_repository
                ),
                order_repository=(
                    order_repository
                ),
                alert_repository=(
                    alert_repository
                ),
                sync_run_repository=(
                    sync_run_repository
                ),
                profit_snapshot_repository=(
                    profit_snapshot_repository
                ),
            )
        )

        daily_report_result = (
            daily_report_service
            .generate_and_save_report()
        )

        presenter.show_daily_report_success(
            daily_report_result
        )

        report_id = (
            daily_report_result[
                "report_id"
            ]
        )

        health_status = (
            daily_report_result[
                "report"
            ][
                "health"
            ][
                "status"
            ]
        )

        logger.info(
            "Daily reporting workflow completed. "
            "report_id=%s health=%s.",
            report_id,
            health_status,
        )

        return ReportingWorkflowResult(
            success=True,
            report_id=report_id,
            health_status=health_status,
            error_type=None,
            error_message=None,
        )

    except Exception as exc:
        error_type = type(exc).__name__
        error_message = (
            f"{error_type}: {exc}"
        )

        logger.exception(
            "Daily reporting workflow failed "
            "after successful synchronization "
            "run #%s.",
            sync_run_id,
        )

        try:
            presenter.show_daily_report_failure()

        except Exception:
            logger.exception(
                "Secondary reporting failure: "
                "could not render the daily-report "
                "failure message for run #%s.",
                sync_run_id,
            )

        return ReportingWorkflowResult(
            success=False,
            report_id=None,
            health_status=None,
            error_type=error_type,
            error_message=error_message,
        )
