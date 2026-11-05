from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from application.presentation_ports import (
    SyncWorkflowPresenter,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderSyncState:
    """
    Shopify order data retrieved for the current synchronization run.
    """

    orders: list[dict]

    @property
    def orders_seen(self) -> int:
        """
        Number of Shopify orders retrieved.
        """

        return len(self.orders)


@dataclass(frozen=True)
class OrderPersistenceResult:
    """
    Result of persisting Shopify orders into SQLite.
    """

    new_orders: list[dict]

    @property
    def new_orders_detected(self) -> int:
        """
        Number of orders first seen during this synchronization.
        """

        return len(self.new_orders)


@dataclass(frozen=True)
class NewOrderAlertResult:
    """
    Result of creating persistent alerts for newly detected orders.
    """

    alerts: list[dict]

    @property
    def alerts_processed(self) -> int:
        """
        Number of new-order alerts created/processed.
        """

        return len(self.alerts)


@dataclass(frozen=True)
class OrderPersistenceSnapshot:
    """
    SQLite order state used for later persistence verification.
    """

    stored_order_count: int
    stored_line_item_count: int
    expected_line_item_count: int


@dataclass(frozen=True)
class OrderVerificationResult:
    """
    Verified order and line-item counts returned to the coordinator.
    """

    orders_seen: int
    line_items_seen: int


def retrieve_orders(
    *,
    order_service: Any,
    presenter: SyncWorkflowPresenter,
) -> OrderSyncState:
    """
    Retrieve Shopify orders and present the retrieval result.
    """

    presenter.show_order_retrieval_started()

    orders = (
        order_service
        .get_all_orders()
    )

    logger.info(
        "Retrieved %s orders from Shopify.",
        len(orders),
    )

    presenter.show_order_retrieval_result(
        orders
    )

    return OrderSyncState(
        orders=orders,
    )


def persist_orders(
    *,
    order_state: OrderSyncState,
    order_repository: Any,
    presenter: SyncWorkflowPresenter,
) -> OrderPersistenceResult:
    """
    Persist Shopify orders and identify orders first seen in this run.
    """

    presenter.show_order_persistence_started()

    new_orders = []

    for order in order_state.orders:
        is_new_order = (
            order_repository.save_order(
                order
            )
        )

        if is_new_order:
            new_orders.append(
                order
            )

    presenter.show_order_persistence_success()

    logger.info(
        (
            "Order persistence completed. "
            "orders=%s new_orders=%s"
        ),
        order_state.orders_seen,
        len(new_orders),
    )

    return OrderPersistenceResult(
        new_orders=new_orders,
    )


def process_new_order_alerts(
    *,
    persistence_result: OrderPersistenceResult,
    alert_service: Any,
    presenter: SyncWorkflowPresenter,
) -> NewOrderAlertResult:
    """
    Present newly detected orders and create persistent order alerts.
    """

    presenter.show_new_order_detection(
        persistence_result.new_orders
    )

    presenter.show_new_order_alert_processing_started()

    alerts = []

    for order in persistence_result.new_orders:
        alert = (
            alert_service
            .create_new_order_alert(
                order
            )
        )

        alerts.append(
            alert
        )

        presenter.show_new_order_alert_created(
            order_name=order["name"],
            alert_id=alert["id"],
        )

    presenter.show_new_order_alert_summary(
        len(alerts)
    )

    logger.info(
        (
            "New-order alert processing completed. "
            "new_orders=%s alerts_processed=%s"
        ),
        persistence_result.new_orders_detected,
        len(alerts),
    )

    return NewOrderAlertResult(
        alerts=alerts,
    )


def read_order_persistence_state(
    *,
    order_state: OrderSyncState,
    order_repository: Any,
) -> OrderPersistenceSnapshot:
    """
    Read SQLite order counts for later verification.

    Presentation is intentionally deferred so the coordinator preserves
    the existing product-read -> order-read -> product-verify ->
    order-verify execution and terminal-output order.
    """

    stored_order_count = (
        order_repository
        .count_orders()
    )

    stored_line_item_count = (
        order_repository
        .count_line_items()
    )

    expected_line_item_count = sum(
        len(
            order[
                "lineItems"
            ][
                "edges"
            ]
        )
        for order in order_state.orders
    )

    return OrderPersistenceSnapshot(
        stored_order_count=(
            stored_order_count
        ),
        stored_line_item_count=(
            stored_line_item_count
        ),
        expected_line_item_count=(
            expected_line_item_count
        ),
    )


def verify_order_persistence(
    *,
    order_state: OrderSyncState,
    persistence_snapshot: OrderPersistenceSnapshot,
    presenter: SyncWorkflowPresenter,
) -> OrderVerificationResult:
    """
    Verify Shopify order/line-item counts against SQLite state.

    Raises the same RuntimeError message as the original coordinator so
    the established synchronization failure boundary remains unchanged.
    """

    presenter.show_order_database_verification(
        shopify_orders=(
            order_state.orders_seen
        ),
        database_orders=(
            persistence_snapshot
            .stored_order_count
        ),
        shopify_line_items=(
            persistence_snapshot
            .expected_line_item_count
        ),
        database_line_items=(
            persistence_snapshot
            .stored_line_item_count
        ),
    )

    orders_match = (
        order_state.orders_seen
        == persistence_snapshot
        .stored_order_count
    )

    line_items_match = (
        persistence_snapshot
        .expected_line_item_count
        == persistence_snapshot
        .stored_line_item_count
    )

    if not (
        orders_match
        and line_items_match
    ):
        raise RuntimeError(
            "Shopify and SQLite order "
            "record counts do not match."
        )

    presenter.show_order_database_verification_success()

    return OrderVerificationResult(
        orders_seen=(
            order_state.orders_seen
        ),
        line_items_seen=(
            persistence_snapshot
            .expected_line_item_count
        ),
    )
