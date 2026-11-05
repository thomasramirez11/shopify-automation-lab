from __future__ import annotations

from presentation.terminal_presenter import (
    show_active_low_inventory_alert,
    show_alert_database_status,
    show_daily_report_failure,
    show_daily_report_success,
    show_financial_analysis_started,
    show_financial_processing_count,
    show_financial_results,
    show_financial_snapshot_status,
    show_low_inventory_processing_started,
    show_low_inventory_summary,
    show_missing_cost_alert_summary,
    show_new_order_alert_created,
    show_new_order_alert_processing_started,
    show_new_order_alert_summary,
    show_new_order_detection,
    show_order_database_verification,
    show_order_database_verification_success,
    show_order_persistence_started,
    show_order_persistence_success,
    show_order_retrieval_result,
    show_order_retrieval_started,
    show_product_database_verification,
    show_product_database_verification_success,
    show_product_persistence_started,
    show_product_persistence_success,
    show_product_retrieval_result,
    show_product_retrieval_started,
    show_recent_sync_runs,
    show_resolved_low_inventory_alert,
    show_sync_audit,
    show_sync_failure,
)


class TerminalWorkflowPresenter:
    """
    CLI adapter for application-layer presentation ports.

    The application workflows depend only on Protocol contracts.
    This adapter translates those contracts to the existing terminal
    presentation functions.

    The class intentionally has no state, so one instance can be shared
    across synchronization, reporting, and failure workflows.
    """

    show_product_retrieval_started = staticmethod(
        show_product_retrieval_started
    )
    show_product_retrieval_result = staticmethod(
        show_product_retrieval_result
    )
    show_order_retrieval_started = staticmethod(
        show_order_retrieval_started
    )
    show_order_retrieval_result = staticmethod(
        show_order_retrieval_result
    )

    show_product_persistence_started = staticmethod(
        show_product_persistence_started
    )
    show_product_persistence_success = staticmethod(
        show_product_persistence_success
    )
    show_order_persistence_started = staticmethod(
        show_order_persistence_started
    )
    show_order_persistence_success = staticmethod(
        show_order_persistence_success
    )

    show_low_inventory_processing_started = staticmethod(
        show_low_inventory_processing_started
    )
    show_active_low_inventory_alert = staticmethod(
        show_active_low_inventory_alert
    )
    show_resolved_low_inventory_alert = staticmethod(
        show_resolved_low_inventory_alert
    )
    show_low_inventory_summary = staticmethod(
        show_low_inventory_summary
    )

    show_new_order_detection = staticmethod(
        show_new_order_detection
    )
    show_new_order_alert_processing_started = staticmethod(
        show_new_order_alert_processing_started
    )
    show_new_order_alert_created = staticmethod(
        show_new_order_alert_created
    )
    show_new_order_alert_summary = staticmethod(
        show_new_order_alert_summary
    )

    show_financial_analysis_started = staticmethod(
        show_financial_analysis_started
    )
    show_financial_processing_count = staticmethod(
        show_financial_processing_count
    )
    show_missing_cost_alert_summary = staticmethod(
        show_missing_cost_alert_summary
    )
    show_financial_results = staticmethod(
        show_financial_results
    )
    show_financial_snapshot_status = staticmethod(
        show_financial_snapshot_status
    )
    show_alert_database_status = staticmethod(
        show_alert_database_status
    )

    show_product_database_verification = staticmethod(
        show_product_database_verification
    )
    show_product_database_verification_success = staticmethod(
        show_product_database_verification_success
    )
    show_order_database_verification = staticmethod(
        show_order_database_verification
    )
    show_order_database_verification_success = staticmethod(
        show_order_database_verification_success
    )

    show_sync_audit = staticmethod(
        show_sync_audit
    )
    show_recent_sync_runs = staticmethod(
        show_recent_sync_runs
    )

    show_daily_report_success = staticmethod(
        show_daily_report_success
    )
    show_daily_report_failure = staticmethod(
        show_daily_report_failure
    )

    show_sync_failure = staticmethod(
        show_sync_failure
    )
