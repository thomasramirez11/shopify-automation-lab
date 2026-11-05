from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from application.financial_workflow import (
    process_financial_workflow,
)
from application.inventory_alert_workflow import (
    process_inventory_alerts,
)
from application.order_sync_workflow import (
    persist_orders,
    process_new_order_alerts,
    retrieve_orders,
)
from application.presentation_ports import SyncWorkflowPresenter
from application.product_sync_workflow import (
    persist_products,
    retrieve_products,
)
from application.sync_completion_workflow import (
    complete_synchronization,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncWorkflowResult:
    """
    Summary of one successful authenticated synchronization workflow.

    The result object gives tests and future interfaces a compact,
    presentation-independent description of what the workflow processed.
    """

    products_seen: int
    variants_seen: int
    orders_seen: int
    line_items_seen: int
    new_orders_detected: int
    financial_results_processed: int
    profit_snapshots_stored: int
    open_alerts: int
    total_alert_history: int


def run_synchronization_workflow(
    *,
    sync_run_id: int,
    product_service: Any,
    order_service: Any,
    product_repository: Any,
    order_repository: Any,
    profit_snapshot_repository: Any,
    financial_processing_service: Any,
    alert_repository: Any,
    alert_service: Any,
    sync_run_repository: Any,
    presenter: SyncWorkflowPresenter,
) -> SyncWorkflowResult:
    """
    Run the authenticated Shopify-to-SQLite synchronization workflow.

    This function owns the successful synchronization path after Shopify
    authentication and dependency construction.

    It intentionally does NOT:
        - create the sync audit row
        - authenticate with Shopify
        - handle the top-level failure boundary
        - generate the post-success daily report

    Those responsibilities remain in main.py so existing failure
    semantics and reporting isolation stay unchanged.
    """

    # --------------------------------------------------
    # 6-7. Retrieve and present Shopify products
    # --------------------------------------------------

    product_state = retrieve_products(
        product_service=product_service,
        presenter=presenter,
    )

    products = product_state.products

    # --------------------------------------------------
    # 8-9. Retrieve and present Shopify orders
    # --------------------------------------------------

    order_state = retrieve_orders(
        order_service=order_service,
        presenter=presenter,
    )

    orders = order_state.orders

    # --------------------------------------------------
    # 10. Persist Shopify products into SQLite
    # --------------------------------------------------

    persist_products(
        product_state=product_state,
        product_repository=(
            product_repository
        ),
        presenter=presenter,
    )

    # --------------------------------------------------
    # 10B. Keep low-inventory alerts synchronized
    # --------------------------------------------------

    inventory_alert_result = (
        process_inventory_alerts(
            product_state=product_state,
            alert_service=alert_service,
            presenter=presenter,
        )
    )

    # --------------------------------------------------
    # 11. Persist Shopify orders and detect new orders
    # --------------------------------------------------

    order_persistence_result = (
        persist_orders(
            order_state=order_state,
            order_repository=(
                order_repository
            ),
            presenter=presenter,
        )
    )

    new_orders = (
        order_persistence_result
        .new_orders
    )

    # --------------------------------------------------
    # 12-13. Present new orders and synchronize alerts
    # --------------------------------------------------

    new_order_alert_result = (
        process_new_order_alerts(
            persistence_result=(
                order_persistence_result
            ),
            alert_service=alert_service,
            presenter=presenter,
        )
    )

    # --------------------------------------------------
    # 14-16. Process finances, missing-cost alerts,
    # and profit-snapshot status
    # --------------------------------------------------

    financial_workflow_result = (
        process_financial_workflow(
            order_repository=(
                order_repository
            ),
            financial_processing_service=(
                financial_processing_service
            ),
            alert_service=alert_service,
            profit_snapshot_repository=(
                profit_snapshot_repository
            ),
            presenter=presenter,
        )
    )

    # --------------------------------------------------
    # Complete verification, audit, and sync history
    # --------------------------------------------------

    completion_result = (
        complete_synchronization(
            sync_run_id=sync_run_id,
            product_state=product_state,
            order_state=order_state,
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
            profit_snapshots_stored=(
                financial_workflow_result
                .profit_snapshots_stored
            ),
            presenter=presenter,
        )
    )

    return SyncWorkflowResult(
        products_seen=(
            completion_result
            .products_seen
        ),
        variants_seen=(
            completion_result
            .variants_seen
        ),
        orders_seen=(
            completion_result
            .orders_seen
        ),
        line_items_seen=(
            completion_result
            .line_items_seen
        ),
        new_orders_detected=(
            order_persistence_result
            .new_orders_detected
        ),
        financial_results_processed=(
            financial_workflow_result
            .financial_results_processed
        ),
        profit_snapshots_stored=(
            financial_workflow_result
            .profit_snapshots_stored
        ),
        open_alerts=(
            completion_result
            .open_alerts
        ),
        total_alert_history=(
            completion_result
            .total_alert_history
        ),
    )

