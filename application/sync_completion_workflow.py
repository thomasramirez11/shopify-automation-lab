from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from application.order_sync_workflow import (
    OrderSyncState,
    read_order_persistence_state,
    verify_order_persistence,
)
from application.presentation_ports import (
    SyncWorkflowPresenter,
)
from application.product_sync_workflow import (
    ProductSyncState,
    read_product_persistence_state,
    verify_product_persistence,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncCompletionResult:
    """
    Verified counts and audit totals for one successful sync completion.
    """

    products_seen: int
    variants_seen: int
    orders_seen: int
    line_items_seen: int
    open_alerts: int
    total_alert_history: int


def complete_synchronization(
    *,
    sync_run_id: int,
    product_state: ProductSyncState,
    order_state: OrderSyncState,
    product_repository: Any,
    order_repository: Any,
    alert_repository: Any,
    sync_run_repository: Any,
    profit_snapshots_stored: int,
    presenter: SyncWorkflowPresenter,
) -> SyncCompletionResult:
    """
    Verify persisted state and finalize the synchronization audit.

    Execution order intentionally matches the original coordinator:

        1. Read/display alert totals
        2. Read product persistence state
        3. Read order persistence state
        4. Verify products
        5. Verify orders
        6. Mark sync run successful
        7. Display completed sync audit
        8. Display recent synchronization history

    A verification failure therefore still prevents mark_success().
    """

    open_alert_count = (
        alert_repository
        .count_open_alerts()
    )

    total_alert_count = (
        alert_repository
        .count_all_alerts()
    )

    presenter.show_alert_database_status(
        open_alert_count=open_alert_count,
        total_alert_count=total_alert_count,
    )

    logger.info(
        "Alert counts. open=%s total_history=%s",
        open_alert_count,
        total_alert_count,
    )

    product_persistence_snapshot = (
        read_product_persistence_state(
            product_state=product_state,
            product_repository=(
                product_repository
            ),
        )
    )

    order_persistence_snapshot = (
        read_order_persistence_state(
            order_state=order_state,
            order_repository=(
                order_repository
            ),
        )
    )

    product_verification = (
        verify_product_persistence(
            product_state=product_state,
            persistence_snapshot=(
                product_persistence_snapshot
            ),
            presenter=presenter,
        )
    )

    order_verification = (
        verify_order_persistence(
            order_state=order_state,
            persistence_snapshot=(
                order_persistence_snapshot
            ),
            presenter=presenter,
        )
    )

    sync_run_repository.mark_success(
        run_id=sync_run_id,
        products_seen=(
            product_verification
            .products_seen
        ),
        variants_seen=(
            product_verification
            .variants_seen
        ),
    )

    logger.info(
        (
            "Synchronization run #%s completed successfully. "
            "products=%s variants=%s orders=%s line_items=%s "
            "profit_snapshots=%s"
        ),
        sync_run_id,
        product_verification.products_seen,
        product_verification.variants_seen,
        order_verification.orders_seen,
        order_verification.line_items_seen,
        profit_snapshots_stored,
    )

    completed_sync_run = (
        sync_run_repository
        .get_run_by_id(
            sync_run_id
        )
    )

    presenter.show_sync_audit(
        completed_sync_run
    )

    recent_runs = (
        sync_run_repository
        .get_recent_runs(
            limit=5
        )
    )

    presenter.show_recent_sync_runs(
        recent_runs
    )

    return SyncCompletionResult(
        products_seen=(
            product_verification
            .products_seen
        ),
        variants_seen=(
            product_verification
            .variants_seen
        ),
        orders_seen=(
            order_verification
            .orders_seen
        ),
        line_items_seen=(
            order_verification
            .line_items_seen
        ),
        open_alerts=open_alert_count,
        total_alert_history=(
            total_alert_count
        ),
    )
