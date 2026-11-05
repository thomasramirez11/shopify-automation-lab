from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SyncWorkflowPresenter(Protocol):
    """
    Presentation contract used by the synchronization workflow.

    The application layer depends on this interface instead of a
    concrete terminal implementation. A CLI, web API, dashboard,
    test double, or future Shopify app adapter can satisfy the same
    contract.
    """

    def show_product_retrieval_started(self) -> None: ...
    def show_product_retrieval_result(self, products: list[dict]) -> None: ...
    def show_order_retrieval_started(self) -> None: ...
    def show_order_retrieval_result(self, orders: list[dict]) -> None: ...

    def show_product_persistence_started(self) -> None: ...
    def show_product_persistence_success(self) -> None: ...
    def show_order_persistence_started(self) -> None: ...
    def show_order_persistence_success(self) -> None: ...

    def show_low_inventory_processing_started(
        self,
        threshold: int,
    ) -> None: ...

    def show_active_low_inventory_alert(
        self,
        alert: dict,
    ) -> None: ...

    def show_resolved_low_inventory_alert(
        self,
        *,
        sku: str | None,
        inventory_quantity: int,
    ) -> None: ...

    def show_low_inventory_summary(
        self,
        *,
        inventory_variants_checked: int,
        untracked_variants_skipped: int,
        processed_count: int,
        resolved_count: int,
    ) -> None: ...

    def show_new_order_detection(
        self,
        new_orders: list[dict],
    ) -> None: ...

    def show_new_order_alert_processing_started(self) -> None: ...

    def show_new_order_alert_created(
        self,
        *,
        order_name: str,
        alert_id: int,
    ) -> None: ...

    def show_new_order_alert_summary(
        self,
        processed_count: int,
    ) -> None: ...

    def show_financial_analysis_started(self) -> None: ...

    def show_financial_processing_count(
        self,
        processed_count: int,
    ) -> None: ...

    def show_missing_cost_alert_summary(
        self,
        *,
        processed_alerts: list[dict],
        resolved_items: list[dict],
    ) -> None: ...

    def show_financial_results(
        self,
        financial_results: list[dict],
    ) -> None: ...

    def show_financial_snapshot_status(
        self,
        stored_snapshot_count: int,
    ) -> None: ...

    def show_alert_database_status(
        self,
        *,
        open_alert_count: int,
        total_alert_count: int,
    ) -> None: ...

    def show_product_database_verification(
        self,
        *,
        shopify_products: int,
        database_products: int,
        shopify_variants: int,
        database_variants: int,
    ) -> None: ...

    def show_product_database_verification_success(self) -> None: ...

    def show_order_database_verification(
        self,
        *,
        shopify_orders: int,
        database_orders: int,
        shopify_line_items: int,
        database_line_items: int,
    ) -> None: ...

    def show_order_database_verification_success(self) -> None: ...

    def show_sync_audit(
        self,
        completed_sync_run: dict,
    ) -> None: ...

    def show_recent_sync_runs(
        self,
        recent_runs: list[dict],
    ) -> None: ...


@runtime_checkable
class FailurePresenter(Protocol):
    """
    Presentation contract used by failure recovery.
    """

    def show_sync_failure(
        self,
        *,
        sync_run_id: int | None,
        error_message: str,
        sync_run_marked_failed: bool,
        failure_alert: dict | None,
    ) -> None: ...


@runtime_checkable
class ReportingPresenter(Protocol):
    """
    Presentation contract used by post-sync reporting.
    """

    def show_daily_report_success(
        self,
        daily_report_result: dict,
    ) -> None: ...

    def show_daily_report_failure(self) -> None: ...
