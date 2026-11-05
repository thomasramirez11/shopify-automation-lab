from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from application.presentation_ports import FailurePresenter


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FailureHandlingResult:
    """
    Result of the secondary synchronization-failure workflow.

    This object describes what recovery work succeeded without
    replacing or mutating the original exception.
    """

    error_type: str
    error_message: str
    sync_run_marked_failed: bool
    failure_alert: dict | None


def handle_synchronization_failure(
    *,
    error: Exception,
    sync_run_id: int | None,
    sync_run_repository: Any,
    alert_service: Any,
    presenter: FailurePresenter,
) -> FailureHandlingResult:
    """
    Perform best-effort secondary work after a synchronization error.

    Responsibilities:
        - build the persisted error message
        - mark the sync audit as failed when an audit ID exists
        - create/open the persistent sync-failure alert
        - render the final failure state

    Non-responsibilities:
        - logging the original traceback
        - re-raising the original exception

    Those remain in main.py so the primary failure always keeps its
    original traceback and exception identity.
    """

    error_type = type(error).__name__

    error_message = (
        f"{error_type}: {error}"
    )

    sync_run_marked_failed = False
    failure_alert = None

    if sync_run_id is not None:
        try:
            sync_run_repository.mark_failed(
                run_id=sync_run_id,
                error_message=error_message,
            )

            sync_run_marked_failed = True

        except Exception:
            logger.exception(
                "Secondary failure: could not mark "
                "synchronization run #%s as failed.",
                sync_run_id,
            )

        try:
            failure_alert = (
                alert_service
                .create_sync_failure_alert(
                    sync_run_id=sync_run_id,
                    error_type=error_type,
                )
            )

        except Exception:
            logger.exception(
                "Secondary failure: could not persist "
                "SYNC_FAILURE alert for run #%s.",
                sync_run_id,
            )

    else:
        logger.critical(
            "Synchronization failed before a sync-run "
            "audit record could be created."
        )

    presenter.show_sync_failure(
        sync_run_id=sync_run_id,
        error_message=error_message,
        sync_run_marked_failed=(
            sync_run_marked_failed
        ),
        failure_alert=failure_alert,
    )

    return FailureHandlingResult(
        error_type=error_type,
        error_message=error_message,
        sync_run_marked_failed=(
            sync_run_marked_failed
        ),
        failure_alert=failure_alert,
    )
