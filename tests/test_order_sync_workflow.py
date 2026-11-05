import pytest

from application.order_sync_workflow import (
    NewOrderAlertResult,
    OrderPersistenceResult,
    OrderPersistenceSnapshot,
    OrderSyncState,
    persist_orders,
    process_new_order_alerts,
    read_order_persistence_state,
    retrieve_orders,
    verify_order_persistence,
)


class RecordingPresenter:
    def __init__(self):
        self.calls = []

    def show_order_retrieval_started(self):
        self.calls.append(
            ("retrieval_started", None)
        )

    def show_order_retrieval_result(
        self,
        orders,
    ):
        self.calls.append(
            ("retrieval_result", orders)
        )

    def show_order_persistence_started(self):
        self.calls.append(
            ("persistence_started", None)
        )

    def show_order_persistence_success(self):
        self.calls.append(
            ("persistence_success", None)
        )

    def show_new_order_detection(
        self,
        new_orders,
    ):
        self.calls.append(
            ("new_order_detection", new_orders)
        )

    def show_new_order_alert_processing_started(
        self,
    ):
        self.calls.append(
            ("alert_processing_started", None)
        )

    def show_new_order_alert_created(
        self,
        *,
        order_name,
        alert_id,
    ):
        self.calls.append(
            (
                "alert_created",
                {
                    "order_name": order_name,
                    "alert_id": alert_id,
                },
            )
        )

    def show_new_order_alert_summary(
        self,
        processed_count,
    ):
        self.calls.append(
            ("alert_summary", processed_count)
        )

    def show_order_database_verification(
        self,
        **kwargs,
    ):
        self.calls.append(
            ("verification", kwargs)
        )

    def show_order_database_verification_success(
        self,
    ):
        self.calls.append(
            ("verification_success", None)
        )


class FakeOrderService:
    def __init__(
        self,
        *,
        orders=None,
        error=None,
    ):
        self.orders = (
            orders
            if orders is not None
            else []
        )
        self.error = error
        self.calls = 0

    def get_all_orders(self):
        self.calls += 1

        if self.error is not None:
            raise self.error

        return self.orders


class FakeOrderRepository:
    def __init__(
        self,
        *,
        new_order_ids=None,
        stored_order_count=0,
        stored_line_item_count=0,
        fail_on_order_id=None,
    ):
        self.new_order_ids = set(
            new_order_ids or []
        )
        self.stored_order_count = (
            stored_order_count
        )
        self.stored_line_item_count = (
            stored_line_item_count
        )
        self.fail_on_order_id = (
            fail_on_order_id
        )
        self.saved_orders = []

    def save_order(
        self,
        order,
    ):
        if (
            order["id"]
            == self.fail_on_order_id
        ):
            raise RuntimeError(
                "order save failed"
            )

        self.saved_orders.append(
            order
        )

        return (
            order["id"]
            in self.new_order_ids
        )

    def count_orders(self):
        return self.stored_order_count

    def count_line_items(self):
        return self.stored_line_item_count


class FakeAlertService:
    def __init__(self):
        self.orders = []

    def create_new_order_alert(
        self,
        order,
    ):
        self.orders.append(
            order
        )

        return {
            "id": 100 + len(
                self.orders
            ),
        }


def make_order(
    *,
    order_id,
    name=None,
    line_item_count=1,
):
    return {
        "id": order_id,
        "name": (
            name
            or f"#{order_id}"
        ),
        "lineItems": {
            "edges": [
                {
                    "node": {
                        "id": (
                            f"{order_id}-"
                            f"line-{index}"
                        )
                    }
                }
                for index in range(
                    line_item_count
                )
            ]
        },
    }


def test_retrieve_orders_returns_state_and_preserves_output_order():
    orders = [
        make_order(
            order_id="1001",
        )
    ]

    presenter = RecordingPresenter()

    result = retrieve_orders(
        order_service=(
            FakeOrderService(
                orders=orders,
            )
        ),
        presenter=presenter,
    )

    assert isinstance(
        result,
        OrderSyncState,
    )
    assert result.orders is orders
    assert result.orders_seen == 1

    assert presenter.calls == [
        ("retrieval_started", None),
        ("retrieval_result", orders),
    ]


def test_retrieve_orders_propagates_service_failure_without_result_output():
    presenter = RecordingPresenter()

    with pytest.raises(
        RuntimeError,
        match="orders unavailable",
    ):
        retrieve_orders(
            order_service=(
                FakeOrderService(
                    error=RuntimeError(
                        "orders unavailable"
                    )
                )
            ),
            presenter=presenter,
        )

    assert presenter.calls == [
        ("retrieval_started", None),
    ]


def test_persist_orders_detects_only_new_orders():
    orders = [
        make_order(order_id="1001"),
        make_order(order_id="1002"),
    ]

    repository = FakeOrderRepository(
        new_order_ids={"1002"},
    )
    presenter = RecordingPresenter()

    result = persist_orders(
        order_state=OrderSyncState(
            orders=orders,
        ),
        order_repository=repository,
        presenter=presenter,
    )

    assert isinstance(
        result,
        OrderPersistenceResult,
    )
    assert repository.saved_orders == orders
    assert result.new_orders == [
        orders[1],
    ]
    assert result.new_orders_detected == 1

    assert presenter.calls == [
        ("persistence_started", None),
        ("persistence_success", None),
    ]


def test_persist_orders_does_not_report_success_after_repository_failure():
    orders = [
        make_order(order_id="1001"),
        make_order(order_id="1002"),
    ]

    presenter = RecordingPresenter()

    with pytest.raises(
        RuntimeError,
        match="order save failed",
    ):
        persist_orders(
            order_state=OrderSyncState(
                orders=orders,
            ),
            order_repository=(
                FakeOrderRepository(
                    fail_on_order_id="1002",
                )
            ),
            presenter=presenter,
        )

    assert presenter.calls == [
        ("persistence_started", None),
    ]


def test_process_new_order_alerts_creates_one_alert_per_new_order():
    orders = [
        make_order(
            order_id="1001",
            name="#1001",
        ),
        make_order(
            order_id="1002",
            name="#1002",
        ),
    ]

    presenter = RecordingPresenter()
    alert_service = FakeAlertService()

    result = process_new_order_alerts(
        persistence_result=(
            OrderPersistenceResult(
                new_orders=orders,
            )
        ),
        alert_service=alert_service,
        presenter=presenter,
    )

    assert isinstance(
        result,
        NewOrderAlertResult,
    )
    assert result.alerts_processed == 2
    assert alert_service.orders == orders

    assert presenter.calls[0] == (
        "new_order_detection",
        orders,
    )
    assert presenter.calls[1] == (
        "alert_processing_started",
        None,
    )
    assert presenter.calls[-1] == (
        "alert_summary",
        2,
    )


def test_process_new_order_alerts_handles_zero_new_orders():
    presenter = RecordingPresenter()
    alert_service = FakeAlertService()

    result = process_new_order_alerts(
        persistence_result=(
            OrderPersistenceResult(
                new_orders=[],
            )
        ),
        alert_service=alert_service,
        presenter=presenter,
    )

    assert result.alerts_processed == 0
    assert alert_service.orders == []

    assert presenter.calls == [
        ("new_order_detection", []),
        ("alert_processing_started", None),
        ("alert_summary", 0),
    ]


def test_read_order_persistence_state_counts_expected_line_items():
    orders = [
        make_order(
            order_id="1001",
            line_item_count=1,
        ),
        make_order(
            order_id="1002",
            line_item_count=3,
        ),
    ]

    snapshot = (
        read_order_persistence_state(
            order_state=(
                OrderSyncState(
                    orders=orders,
                )
            ),
            order_repository=(
                FakeOrderRepository(
                    stored_order_count=2,
                    stored_line_item_count=4,
                )
            ),
        )
    )

    assert isinstance(
        snapshot,
        OrderPersistenceSnapshot,
    )
    assert snapshot.stored_order_count == 2
    assert snapshot.stored_line_item_count == 4
    assert snapshot.expected_line_item_count == 4


def test_verify_order_persistence_returns_verified_counts():
    presenter = RecordingPresenter()

    result = verify_order_persistence(
        order_state=(
            OrderSyncState(
                orders=[
                    make_order(
                        order_id="1001",
                        line_item_count=2,
                    )
                ]
            )
        ),
        persistence_snapshot=(
            OrderPersistenceSnapshot(
                stored_order_count=1,
                stored_line_item_count=2,
                expected_line_item_count=2,
            )
        ),
        presenter=presenter,
    )

    assert result.orders_seen == 1
    assert result.line_items_seen == 2
    assert presenter.calls[-1] == (
        "verification_success",
        None,
    )


def test_verify_order_persistence_rejects_order_count_mismatch():
    presenter = RecordingPresenter()

    with pytest.raises(
        RuntimeError,
        match=(
            "Shopify and SQLite order "
            "record counts do not match"
        ),
    ):
        verify_order_persistence(
            order_state=(
                OrderSyncState(
                    orders=[
                        make_order(
                            order_id="1001",
                        )
                    ]
                )
            ),
            persistence_snapshot=(
                OrderPersistenceSnapshot(
                    stored_order_count=0,
                    stored_line_item_count=1,
                    expected_line_item_count=1,
                )
            ),
            presenter=presenter,
        )

    assert (
        "verification_success",
        None,
    ) not in presenter.calls


def test_verify_order_persistence_rejects_line_item_count_mismatch():
    presenter = RecordingPresenter()

    with pytest.raises(
        RuntimeError,
        match=(
            "Shopify and SQLite order "
            "record counts do not match"
        ),
    ):
        verify_order_persistence(
            order_state=(
                OrderSyncState(
                    orders=[
                        make_order(
                            order_id="1001",
                            line_item_count=2,
                        )
                    ]
                )
            ),
            persistence_snapshot=(
                OrderPersistenceSnapshot(
                    stored_order_count=1,
                    stored_line_item_count=1,
                    expected_line_item_count=2,
                )
            ),
            presenter=presenter,
        )

    assert (
        "verification_success",
        None,
    ) not in presenter.calls
