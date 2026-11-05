from application.financial_workflow import (
    FinancialWorkflowResult,
    process_financial_workflow,
)


class RecordingPresenter:
    def __init__(self):
        self.calls = []

    def show_financial_analysis_started(
        self,
    ):
        self.calls.append(
            ("started", None)
        )

    def show_financial_processing_count(
        self,
        count,
    ):
        self.calls.append(
            ("processed_count", count)
        )

    def show_missing_cost_alert_summary(
        self,
        *,
        processed_alerts,
        resolved_items,
    ):
        self.calls.append(
            (
                "missing_cost_summary",
                {
                    "processed_alerts":
                        processed_alerts,
                    "resolved_items":
                        resolved_items,
                },
            )
        )

    def show_financial_results(
        self,
        results,
    ):
        self.calls.append(
            ("results", results)
        )

    def show_financial_snapshot_status(
        self,
        count,
    ):
        self.calls.append(
            ("snapshot_count", count)
        )


class FakeOrderRepository:
    def __init__(
        self,
        orders,
    ):
        self.orders = orders
        self.calls = 0

    def get_all_orders(self):
        self.calls += 1
        return self.orders


class FakeFinancialProcessingService:
    def __init__(
        self,
        results_by_id,
    ):
        self.results_by_id = (
            results_by_id
        )
        self.calls = []

    def process_order(
        self,
        order,
    ):
        self.calls.append(
            order["id"]
        )

        result = self.results_by_id[
            order["id"]
        ]

        if isinstance(
            result,
            Exception,
        ):
            raise result

        return result


class FakeAlertService:
    def __init__(
        self,
        *,
        resolve_result=True,
    ):
        self.resolve_result = (
            resolve_result
        )
        self.created = []
        self.resolved = []

    def create_missing_cost_alert(
        self,
        *,
        order_name,
        missing_item,
    ):
        self.created.append(
            {
                "order_name": order_name,
                "missing_item":
                    missing_item,
            }
        )

        return {
            "id": 31,
            "title": "Missing cost",
            "occurrence_count": 1,
        }

    def resolve_missing_cost_alert(
        self,
        *,
        sku,
        variant_id,
    ):
        self.resolved.append(
            {
                "sku": sku,
                "variant_id": variant_id,
            }
        )

        return self.resolve_result


class FakeProfitSnapshotRepository:
    def __init__(
        self,
        count,
    ):
        self.count = count
        self.calls = 0

    def count_snapshots(self):
        self.calls += 1
        return self.count


def make_order(
    order_id,
):
    return {
        "id": order_id,
    }


def make_result(
    *,
    order_name="#1001",
    item_results=None,
    missing_cost_count=0,
    snapshots_created=1,
    existing_snapshots=0,
):
    return {
        "order_name": order_name,
        "financial_status": (
            "incomplete"
            if missing_cost_count
            else "complete"
        ),
        "line_items_seen": 1,
        "snapshots_created":
            snapshots_created,
        "existing_snapshots":
            existing_snapshots,
        "missing_cost_count":
            missing_cost_count,
        "missing_cost_items": [],
        "item_results": (
            item_results
            if item_results is not None
            else []
        ),
        "summary": None,
    }


def run_case(
    *,
    orders,
    results_by_id,
    snapshot_count=0,
    resolve_result=True,
):
    presenter = RecordingPresenter()
    alert_service = FakeAlertService(
        resolve_result=resolve_result,
    )

    result = process_financial_workflow(
        order_repository=(
            FakeOrderRepository(
                orders
            )
        ),
        financial_processing_service=(
            FakeFinancialProcessingService(
                results_by_id
            )
        ),
        alert_service=alert_service,
        profit_snapshot_repository=(
            FakeProfitSnapshotRepository(
                snapshot_count
            )
        ),
        presenter=presenter,
    )

    return (
        result,
        alert_service,
        presenter,
    )


def test_empty_order_set_returns_zero_financial_results():
    result, service, presenter = (
        run_case(
            orders=[],
            results_by_id={},
            snapshot_count=4,
        )
    )

    assert isinstance(
        result,
        FinancialWorkflowResult,
    )

    assert (
        result.financial_results_processed
        == 0
    )
    assert (
        result.missing_cost_alerts_processed
        == 0
    )
    assert (
        result.missing_cost_alerts_resolved
        == 0
    )
    assert (
        result.profit_snapshots_stored
        == 4
    )

    assert service.created == []
    assert service.resolved == []

    assert presenter.calls == [
        ("started", None),
        ("processed_count", 0),
        (
            "missing_cost_summary",
            {
                "processed_alerts": [],
                "resolved_items": [],
            },
        ),
        ("results", []),
        ("snapshot_count", 4),
    ]


def test_missing_cost_item_creates_alert():
    order = make_order(
        "order-1"
    )

    missing_item = {
        "status": "missing_cost",
        "sku": "SKU-1",
        "shopify_variant_id":
            "variant-1",
    }

    result, service, _ = run_case(
        orders=[order],
        results_by_id={
            "order-1": make_result(
                item_results=[
                    missing_item
                ],
                missing_cost_count=1,
                snapshots_created=0,
            )
        },
    )

    assert (
        result.missing_cost_alerts_processed
        == 1
    )

    assert service.created == [
        {
            "order_name": "#1001",
            "missing_item":
                missing_item,
        }
    ]


def test_created_snapshot_item_resolves_missing_cost_alert():
    item = {
        "status": "created",
        "sku": "SKU-1",
        "shopify_variant_id":
            "variant-1",
    }

    result, service, presenter = run_case(
        orders=[
            make_order(
                "order-1"
            )
        ],
        results_by_id={
            "order-1": make_result(
                item_results=[item],
            )
        },
    )

    assert (
        result.missing_cost_alerts_resolved
        == 1
    )

    assert service.resolved == [
        {
            "sku": "SKU-1",
            "variant_id":
                "variant-1",
        }
    ]

    summary = next(
        payload
        for name, payload
        in presenter.calls
        if name
        == "missing_cost_summary"
    )

    assert len(
        summary["resolved_items"]
    ) == 1


def test_existing_snapshot_item_can_resolve_missing_cost_alert():
    item = {
        "status":
            "existing_snapshot",
        "sku": "SKU-2",
        "shopify_variant_id":
            "variant-2",
    }

    result, service, _ = run_case(
        orders=[
            make_order(
                "order-2"
            )
        ],
        results_by_id={
            "order-2": make_result(
                order_name="#1002",
                item_results=[item],
                existing_snapshots=1,
            )
        },
    )

    assert (
        result.missing_cost_alerts_resolved
        == 1
    )
    assert len(service.resolved) == 1


def test_item_without_sku_or_variant_id_does_not_attempt_resolution():
    item = {
        "status": "created",
        "sku": None,
        "shopify_variant_id": None,
    }

    result, service, _ = run_case(
        orders=[
            make_order(
                "order-1"
            )
        ],
        results_by_id={
            "order-1": make_result(
                item_results=[item],
            )
        },
    )

    assert (
        result.missing_cost_alerts_resolved
        == 0
    )
    assert service.resolved == []


def test_unsuccessful_resolution_is_not_counted():
    item = {
        "status": "created",
        "sku": "SKU-1",
        "shopify_variant_id":
            "variant-1",
    }

    result, service, _ = run_case(
        orders=[
            make_order(
                "order-1"
            )
        ],
        results_by_id={
            "order-1": make_result(
                item_results=[item],
            )
        },
        resolve_result=False,
    )

    assert len(service.resolved) == 1
    assert (
        result.missing_cost_alerts_resolved
        == 0
    )


def test_multiple_orders_preserve_financial_results_and_count():
    orders = [
        make_order("order-1"),
        make_order("order-2"),
    ]

    first = make_result(
        order_name="#1001",
    )
    second = make_result(
        order_name="#1002",
    )

    result, _, presenter = run_case(
        orders=orders,
        results_by_id={
            "order-1": first,
            "order-2": second,
        },
        snapshot_count=2,
    )

    assert (
        result.financial_results
        == [first, second]
    )

    assert (
        result.financial_results_processed
        == 2
    )

    assert (
        ("processed_count", 2)
        in presenter.calls
    )

    assert (
        ("results", [first, second])
        in presenter.calls
    )


def test_financial_service_failure_propagates_before_completion_output():
    presenter = RecordingPresenter()

    order_repository = (
        FakeOrderRepository(
            [
                make_order(
                    "order-1"
                )
            ]
        )
    )

    service = (
        FakeFinancialProcessingService(
            {
                "order-1":
                    RuntimeError(
                        "financial failure"
                    )
            }
        )
    )

    try:
        process_financial_workflow(
            order_repository=(
                order_repository
            ),
            financial_processing_service=(
                service
            ),
            alert_service=(
                FakeAlertService()
            ),
            profit_snapshot_repository=(
                FakeProfitSnapshotRepository(
                    0
                )
            ),
            presenter=presenter,
        )

    except RuntimeError as exc:
        assert (
            str(exc)
            == "financial failure"
        )

    else:
        raise AssertionError(
            "Expected financial failure."
        )

    assert presenter.calls == [
        ("started", None),
    ]
