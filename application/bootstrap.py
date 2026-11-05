from __future__ import annotations

from dataclasses import dataclass

from config.settings import (
    LOW_INVENTORY_THRESHOLD,
    SHOPIFY_API_VERSION,
    SHOPIFY_CLIENT_ID,
    SHOPIFY_CLIENT_SECRET,
    SHOPIFY_STORE_DOMAIN,
)
from repositories.alert_repository import AlertRepository
from repositories.cost_repository import CostRepository
from repositories.daily_report_repository import DailyReportRepository
from repositories.order_repository import OrderRepository
from repositories.product_repository import ProductRepository
from repositories.profit_snapshot_repository import (
    ProfitSnapshotRepository,
)
from repositories.sync_run_repository import SyncRunRepository
from services.alert_service import AlertService
from services.daily_report_service import DailyReportService
from services.financial_processing_service import (
    FinancialProcessingService,
)
from services.order_service import OrderService
from services.product_service import ProductService
from services.profit_service import ProfitService
from services.report_formatter import TerminalReportFormatter
from services.report_service import ReportService
from shopify.client import ShopifyClient


REPORT_RECENT_CHANGE_LIMIT = 10
TERMINAL_RECENT_CHANGES_TO_SHOW = 5


@dataclass(frozen=True)
class FailureSafeDependencies:
    """
    Dependencies required before the main synchronization starts.

    These objects intentionally exist before the synchronization
    try/except boundary so failures can still be audited and alerted.
    """

    sync_run_repository: SyncRunRepository
    alert_repository: AlertRepository
    alert_service: AlertService


@dataclass(frozen=True)
class CoreDependencies:
    """
    Runtime dependencies used by the main Shopify synchronization flow.

    Internal construction-only objects such as CostRepository and
    ProfitService are intentionally not exposed because main.py does
    not use them directly.
    """

    product_service: ProductService
    order_service: OrderService
    product_repository: ProductRepository
    order_repository: OrderRepository
    profit_snapshot_repository: ProfitSnapshotRepository
    financial_processing_service: FinancialProcessingService


def build_failure_safe_dependencies(
    *,
    sync_run_repository_factory=None,
    alert_repository_factory=None,
    alert_service_factory=None,
) -> FailureSafeDependencies:
    """
    Build the minimum dependencies needed for synchronization auditing.

    Optional factories are injection seams for orchestration tests.
    Production callers normally omit them, so the real classes defined
    in this module are used.

    Keeping this function separate preserves the original failure
    boundary from main.py: these dependencies are available even if
    later Shopify/client construction fails.
    """

    if sync_run_repository_factory is None:
        sync_run_repository_factory = (
            SyncRunRepository
        )

    if alert_repository_factory is None:
        alert_repository_factory = (
            AlertRepository
        )

    if alert_service_factory is None:
        alert_service_factory = (
            AlertService
        )

    sync_run_repository = (
        sync_run_repository_factory()
    )

    alert_repository = (
        alert_repository_factory()
    )

    alert_service = (
        alert_service_factory(
            alert_repository=alert_repository,
        )
    )

    return FailureSafeDependencies(
        sync_run_repository=sync_run_repository,
        alert_repository=alert_repository,
        alert_service=alert_service,
    )


def build_shopify_client(
    *,
    shopify_client_factory=None,
) -> ShopifyClient:
    """
    Build the configured Shopify API client.

    The optional factory is a test-injection seam. Production callers
    normally omit it and use the real ShopifyClient class.

    Authentication remains the responsibility of main.py so the
    existing terminal output, logging, and failure timing stay intact.
    """

    if shopify_client_factory is None:
        shopify_client_factory = (
            ShopifyClient
        )

    return shopify_client_factory(
        store_domain=SHOPIFY_STORE_DOMAIN,
        client_id=SHOPIFY_CLIENT_ID,
        client_secret=SHOPIFY_CLIENT_SECRET,
        api_version=SHOPIFY_API_VERSION,
    )


def build_core_dependencies(
    *,
    client: ShopifyClient,
) -> CoreDependencies:
    """
    Build services and repositories used after Shopify authentication.

    This function wires dependencies together but does not execute
    synchronization work, API calls, or reporting.
    """

    product_service = ProductService(
        client
    )

    order_service = OrderService(
        client
    )

    profit_service = ProfitService()

    product_repository = ProductRepository()
    order_repository = OrderRepository()
    cost_repository = CostRepository()

    profit_snapshot_repository = (
        ProfitSnapshotRepository()
    )

    financial_processing_service = (
        FinancialProcessingService(
            order_repository=order_repository,
            cost_repository=cost_repository,
            snapshot_repository=(
                profit_snapshot_repository
            ),
            profit_service=profit_service,
        )
    )

    return CoreDependencies(
        product_service=product_service,
        order_service=order_service,
        product_repository=product_repository,
        order_repository=order_repository,
        profit_snapshot_repository=(
            profit_snapshot_repository
        ),
        financial_processing_service=(
            financial_processing_service
        ),
    )


def build_daily_report_service(
    *,
    product_repository: ProductRepository,
    order_repository: OrderRepository,
    alert_repository: AlertRepository,
    sync_run_repository: SyncRunRepository,
    profit_snapshot_repository: ProfitSnapshotRepository,
) -> DailyReportService:
    """
    Build reporting dependencies only when reporting is ready to run.

    main.py intentionally calls this after a synchronization has already
    been marked successful. This preserves the existing isolated
    reporting failure boundary.
    """

    report_service = ReportService(
        product_repository=product_repository,
        order_repository=order_repository,
        alert_repository=alert_repository,
        sync_run_repository=sync_run_repository,
        profit_snapshot_repository=(
            profit_snapshot_repository
        ),
        low_inventory_threshold=(
            LOW_INVENTORY_THRESHOLD
        ),
        recent_change_limit=(
            REPORT_RECENT_CHANGE_LIMIT
        ),
    )

    report_formatter = TerminalReportFormatter(
        recent_changes_to_show=(
            TERMINAL_RECENT_CHANGES_TO_SHOW
        )
    )

    daily_report_repository = (
        DailyReportRepository()
    )

    return DailyReportService(
        report_service=report_service,
        report_formatter=report_formatter,
        daily_report_repository=(
            daily_report_repository
        ),
    )
