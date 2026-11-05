import pytest

from application.order_sync_workflow import (
    OrderSyncState,
)
from application.product_sync_workflow import (
    ProductSyncState,
)
from application.sync_completion_workflow import (
    SyncCompletionResult,
    complete_synchronization,
)


class RecordingPresenter:
    def __init__(
        self,
        events,
    ):
        self.events = events

    def show_alert_database_status(
        self,
        *,
        open_alert_count,
        total_alert_count,
    ):
        self.events.append(
            (
                "alert_status",
                open_alert_count,
                total_alert_count,
            )
        )

    def show_product_database_verification(
        self,
        **kwargs,
    ):
        self.events.append(
            ("product_verify", kwargs)
        )

    def show_product_database_verification_success(
        self,
    ):
        self.events.append(
            ("product_verify_success",)
        )

    def show_order_database_verification(
        self,
        **kwargs,
    ):
        self.events.append(
            ("order_verify", kwargs)
        )

    def show_order_database_verification_success(
        self,
    ):
        self.events.append(
            ("order_verify_success",)
        )

    def show_sync_audit(
        self,
        run,
    ):
        self.events.append(
            ("sync_audit", run["id"])
        )

    def show_recent_sync_runs(
        self,
        runs,
    ):
        self.events.append(
            (
                "recent_runs",
                [run["id"] for run in runs],
            )
        )


class FakeAlertRepository:
    def __init__(
        self,
        events,
        *,
        open_count=2,
        total_count=7,
    ):
        self.events = events
        self.open_count = open_count
        self.total_count = total_count

    def count_open_alerts(self):
        self.events.append(
            ("count_open_alerts",)
        )
        return self.open_count

    def count_all_alerts(self):
        self.events.append(
            ("count_all_alerts",)
        )
        return self.total_count


class FakeProductRepository:
    def __init__(
        self,
        events,
        *,
        stored_products,
        stored_variants,
    ):
        self.events = events
        self.stored_products = (
            stored_products
        )
        self.stored_variants = (
            stored_variants
        )

    def get_all_products(self):
        self.events.append(
            ("read_products",)
        )
        return self.stored_products

    def get_all_variants(self):
        self.events.append(
            ("read_variants",)
        )
        return self.stored_variants


class FakeOrderRepository:
    def __init__(
        self,
        events,
        *,
        order_count,
        line_item_count,
    ):
        self.events = events
        self.order_count = order_count
        self.line_item_count = (
            line_item_count
        )

    def count_orders(self):
        self.events.append(
            ("count_orders",)
        )
        return self.order_count

    def count_line_items(self):
        self.events.append(
            ("count_line_items",)
        )
        return self.line_item_count


class FakeSyncRunRepository:
    def __init__(
        self,
        events,
        *,
        fail_mark_success=False,
    ):
        self.events = events
        self.fail_mark_success = (
            fail_mark_success
        )
        self.mark_success_calls = []

    def mark_success(
        self,
        *,
        run_id,
        products_seen,
        variants_seen,
    ):
        self.events.append(
            ("mark_success", run_id)
        )

        self.mark_success_calls.append(
            {
                "run_id": run_id,
                "products_seen":
                    products_seen,
                "variants_seen":
                    variants_seen,
            }
        )

        if self.fail_mark_success:
            raise RuntimeError(
                "mark success failed"
            )

    def get_run_by_id(
        self,
        run_id,
    ):
        self.events.append(
            ("get_run_by_id", run_id)
        )

        return {
            "id": run_id,
            "status": "success",
        }

    def get_recent_runs(
        self,
        *,
        limit,
    ):
        self.events.append(
            ("get_recent_runs", limit)
        )

        return [
            {
                "id": 70,
                "status": "success",
            },
            {
                "id": 69,
                "status": "success",
            },
        ]


def make_product(
    *,
    variant_count=2,
):
    return {
        "id": "product-1",
        "variants": {
            "edges": [
                {
                    "node": {
                        "id": (
                            f"variant-{index}"
                        )
                    }
                }
                for index in range(
                    variant_count
                )
            ]
        },
    }


def make_order(
    *,
    line_item_count=2,
):
    return {
        "id": "order-1",
        "lineItems": {
            "edges": [
                {
                    "node": {
                        "id": (
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


def build_dependencies(
    *,
    stored_product_count=1,
    stored_variant_count=2,
    stored_order_count=1,
    stored_line_item_count=2,
    fail_mark_success=False,
):
    events = []

    product_state = ProductSyncState(
        products=[
            make_product(
                variant_count=2,
            )
        ]
    )

    order_state = OrderSyncState(
        orders=[
            make_order(
                line_item_count=2,
            )
        ]
    )

    dependencies = {
        "sync_run_id": 70,
        "product_state":
            product_state,
        "order_state":
            order_state,
        "product_repository":
            FakeProductRepository(
                events,
                stored_products=[
                    {"id": index}
                    for index in range(
                        stored_product_count
                    )
                ],
                stored_variants=[
                    {"id": index}
                    for index in range(
                        stored_variant_count
                    )
                ],
            ),
        "order_repository":
            FakeOrderRepository(
                events,
                order_count=(
                    stored_order_count
                ),
                line_item_count=(
                    stored_line_item_count
                ),
            ),
        "alert_repository":
            FakeAlertRepository(
                events,
                open_count=2,
                total_count=7,
            ),
        "sync_run_repository":
            FakeSyncRunRepository(
                events,
                fail_mark_success=(
                    fail_mark_success
                ),
            ),
        "profit_snapshots_stored":
            4,
        "presenter":
            RecordingPresenter(
                events
            ),
    }

    return events, dependencies


def test_success_returns_verified_completion_result():
    events, dependencies = (
        build_dependencies()
    )

    result = (
        complete_synchronization(
            **dependencies
        )
    )

    assert isinstance(
        result,
        SyncCompletionResult,
    )

    assert result == SyncCompletionResult(
        products_seen=1,
        variants_seen=2,
        orders_seen=1,
        line_items_seen=2,
        open_alerts=2,
        total_alert_history=7,
    )

    assert dependencies[
        "sync_run_repository"
    ].mark_success_calls == [
        {
            "run_id": 70,
            "products_seen": 1,
            "variants_seen": 2,
        }
    ]


def test_completion_preserves_original_phase_order():
    events, dependencies = (
        build_dependencies()
    )

    complete_synchronization(
        **dependencies
    )

    names = [
        event[0]
        for event in events
    ]

    assert names.index(
        "count_open_alerts"
    ) < names.index(
        "read_products"
    )

    assert names.index(
        "read_products"
    ) < names.index(
        "count_orders"
    )

    assert names.index(
        "product_verify"
    ) < names.index(
        "order_verify"
    )

    assert names.index(
        "order_verify_success"
    ) < names.index(
        "mark_success"
    )

    assert names.index(
        "mark_success"
    ) < names.index(
        "sync_audit"
    )

    assert names.index(
        "sync_audit"
    ) < names.index(
        "recent_runs"
    )


def test_product_verification_failure_prevents_mark_success():
    _, dependencies = (
        build_dependencies(
            stored_product_count=0,
        )
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Shopify and SQLite product "
            "record counts do not match"
        ),
    ):
        complete_synchronization(
            **dependencies
        )

    assert (
        dependencies[
            "sync_run_repository"
        ].mark_success_calls
        == []
    )


def test_order_verification_failure_prevents_mark_success():
    _, dependencies = (
        build_dependencies(
            stored_order_count=0,
        )
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Shopify and SQLite order "
            "record counts do not match"
        ),
    ):
        complete_synchronization(
            **dependencies
        )

    assert (
        dependencies[
            "sync_run_repository"
        ].mark_success_calls
        == []
    )


def test_mark_success_failure_prevents_audit_and_history_output():
    events, dependencies = (
        build_dependencies(
            fail_mark_success=True,
        )
    )

    with pytest.raises(
        RuntimeError,
        match="mark success failed",
    ):
        complete_synchronization(
            **dependencies
        )

    names = [
        event[0]
        for event in events
    ]

    assert "mark_success" in names
    assert "get_run_by_id" not in names
    assert "sync_audit" not in names
    assert "get_recent_runs" not in names
    assert "recent_runs" not in names


def test_recent_history_request_keeps_limit_five():
    events, dependencies = (
        build_dependencies()
    )

    complete_synchronization(
        **dependencies
    )

    assert (
        "get_recent_runs",
        5,
    ) in events


def test_alert_counts_are_returned_and_presented():
    events, dependencies = (
        build_dependencies()
    )

    result = complete_synchronization(
        **dependencies
    )

    assert result.open_alerts == 2
    assert result.total_alert_history == 7

    assert (
        "alert_status",
        2,
        7,
    ) in events
