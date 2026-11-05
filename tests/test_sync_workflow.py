import application.sync_workflow as workflow
from config.settings import LOW_INVENTORY_THRESHOLD


class FakeProductService:
    def __init__(self, products):
        self.products = products
        self.calls = 0

    def get_all_products(self):
        self.calls += 1
        return self.products


class FakeOrderService:
    def __init__(self, orders):
        self.orders = orders
        self.calls = 0

    def get_all_orders(self):
        self.calls += 1
        return self.orders


class FakeProductRepository:
    def __init__(
        self,
        *,
        stored_products=None,
        stored_variants=None,
    ):
        self.saved_products = []
        self.stored_products = (
            stored_products
            if stored_products is not None
            else []
        )
        self.stored_variants = (
            stored_variants
            if stored_variants is not None
            else []
        )

    def save_product(self, product):
        self.saved_products.append(product)

    def get_all_products(self):
        return self.stored_products

    def get_all_variants(self):
        return self.stored_variants


class FakeOrderRepository:
    def __init__(
        self,
        *,
        new_order_ids=None,
        stored_orders=None,
        order_count=0,
        line_item_count=0,
    ):
        self.new_order_ids = set(
            new_order_ids or []
        )
        self.saved_orders = []
        self.stored_orders = (
            stored_orders
            if stored_orders is not None
            else []
        )
        self.order_count = order_count
        self.line_item_count = (
            line_item_count
        )

    def save_order(self, order):
        self.saved_orders.append(order)
        return order["id"] in self.new_order_ids

    def get_all_orders(self):
        return self.stored_orders

    def count_orders(self):
        return self.order_count

    def count_line_items(self):
        return self.line_item_count


class FakeProfitSnapshotRepository:
    def __init__(self, count=0):
        self.count = count

    def count_snapshots(self):
        return self.count


class FakeFinancialProcessingService:
    def __init__(self, results_by_order_id):
        self.results_by_order_id = (
            results_by_order_id
        )
        self.calls = []

    def process_order(self, order):
        self.calls.append(order["id"])
        return self.results_by_order_id[
            order["id"]
        ]


class FakeAlertRepository:
    def __init__(
        self,
        *,
        open_count=0,
        total_count=0,
    ):
        self.open_count = open_count
        self.total_count = total_count

    def count_open_alerts(self):
        return self.open_count

    def count_all_alerts(self):
        return self.total_count


class FakeAlertService:
    def __init__(self):
        self.low_inventory_created = []
        self.low_inventory_resolved = []
        self.new_order_alerts = []
        self.missing_cost_created = []
        self.missing_cost_resolved = []

    def create_low_inventory_alert(
        self,
        *,
        product_title,
        variant,
        threshold,
    ):
        self.low_inventory_created.append(
            {
                "product_title": product_title,
                "variant": variant,
                "threshold": threshold,
            }
        )

        return {
            "id": 10,
            "title": (
                "Low inventory for "
                f"{variant.get('sku') or variant['title']}"
            ),
            "occurrence_count": 1,
        }

    def resolve_low_inventory_alert(
        self,
        *,
        sku,
        variant_id,
    ):
        self.low_inventory_resolved.append(
            {
                "sku": sku,
                "variant_id": variant_id,
            }
        )
        return True

    def create_new_order_alert(self, order):
        self.new_order_alerts.append(
            order["id"]
        )

        return {
            "id": 20,
        }

    def create_missing_cost_alert(
        self,
        *,
        order_name,
        missing_item,
    ):
        self.missing_cost_created.append(
            {
                "order_name": order_name,
                "missing_item": missing_item,
            }
        )

        return {
            "id": 30,
            "title": "Missing cost",
            "occurrence_count": 1,
        }

    def resolve_missing_cost_alert(
        self,
        *,
        sku,
        variant_id,
    ):
        self.missing_cost_resolved.append(
            {
                "sku": sku,
                "variant_id": variant_id,
            }
        )
        return True


class FakeSyncRunRepository:
    def __init__(self):
        self.success_calls = []

    def mark_success(
        self,
        *,
        run_id,
        products_seen,
        variants_seen,
    ):
        self.success_calls.append(
            {
                "run_id": run_id,
                "products_seen": products_seen,
                "variants_seen": variants_seen,
            }
        )

    def get_run_by_id(self, run_id):
        return {
            "id": run_id,
            "started_at": "start",
            "completed_at": "end",
            "status": "success",
            "products_seen": (
                self.success_calls[-1][
                    "products_seen"
                ]
            ),
            "variants_seen": (
                self.success_calls[-1][
                    "variants_seen"
                ]
            ),
        }

    def get_recent_runs(self, *, limit):
        assert limit == 5
        return [
            self.get_run_by_id(
                self.success_calls[-1][
                    "run_id"
                ]
            )
        ]


def make_product(
    *,
    product_id="product-001",
    variant_id="variant-001",
    sku="SKU-001",
    inventory_quantity=10,
    tracked=True,
):
    return {
        "id": product_id,
        "title": "Test product",
        "vendor": "Test vendor",
        "status": "ACTIVE",
        "variants": {
            "edges": [
                {
                    "node": {
                        "id": variant_id,
                        "title": "Default Title",
                        "sku": sku,
                        "price": "25.00",
                        "inventoryQuantity": (
                            inventory_quantity
                        ),
                        "inventoryItem": {
                            "tracked": tracked,
                        },
                    }
                }
            ]
        },
    }


def make_order(
    *,
    order_id="order-001",
):
    return {
        "id": order_id,
        "name": "#1001",
        "createdAt": "created",
        "updatedAt": "updated",
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "totalPriceSet": {
            "shopMoney": {
                "amount": "25.00",
                "currencyCode": "USD",
            }
        },
        "lineItems": {
            "edges": [
                {
                    "node": {
                        "id": "line-001",
                        "title": "Test product",
                        "sku": "SKU-001",
                        "quantity": 1,
                        "variant": {
                            "id": "variant-001",
                        },
                        "originalUnitPriceSet": {
                            "shopMoney": {
                                "amount": "25.00",
                                "currencyCode": "USD",
                            }
                        },
                    }
                }
            ]
        },
    }


def complete_financial_result(
    *,
    order_id="order-001",
):
    return {
        "order_name": "#1001",
        "financial_status": "complete",
        "line_items_seen": 1,
        "snapshots_created": 1,
        "existing_snapshots": 0,
        "missing_cost_count": 0,
        "missing_cost_items": [],
        "item_results": [
            {
                "status": "created",
                "sku": "SKU-001",
                "shopify_variant_id": (
                    "variant-001"
                ),
            }
        ],
        "summary": {
            "currency_code": "USD",
            "merchandise_revenue": "25.00",
            "product_cost": "10.00",
            "estimated_gross_profit": "15.00",
            "gross_margin_percent": "60.00",
            "total_quantity": 1,
            "line_items_count": 1,
        },
    }


class SilentPresenter:
    """
    Test presenter that accepts every synchronization
    presentation call without producing terminal output.
    """

    def __getattr__(
        self,
        name,
    ):
        if name.startswith("show_"):
            return lambda *args, **kwargs: None

        raise AttributeError(name)


def build_happy_path(
    monkeypatch,
    *,
    inventory_quantity=10,
    tracked=True,
    new_order=True,
    financial_result=None,
):
    product = make_product(
        inventory_quantity=(
            inventory_quantity
        ),
        tracked=tracked,
    )

    order = make_order()

    product_repository = (
        FakeProductRepository(
            stored_products=[
                {
                    "shopify_product_id":
                        "product-001"
                }
            ],
            stored_variants=[
                {
                    "shopify_variant_id":
                        "variant-001"
                }
            ],
        )
    )

    order_repository = (
        FakeOrderRepository(
            new_order_ids=(
                {"order-001"}
                if new_order
                else set()
            ),
            stored_orders=[
                order
            ],
            order_count=1,
            line_item_count=1,
        )
    )

    if financial_result is None:
        financial_result = (
            complete_financial_result()
        )

    dependencies = {
        "sync_run_id": 61,
        "product_service":
            FakeProductService([product]),
        "order_service":
            FakeOrderService([order]),
        "product_repository":
            product_repository,
        "order_repository":
            order_repository,
        "profit_snapshot_repository":
            FakeProfitSnapshotRepository(
                count=1
            ),
        "financial_processing_service":
            FakeFinancialProcessingService(
                {
                    "order-001":
                        financial_result
                }
            ),
        "alert_repository":
            FakeAlertRepository(
                open_count=2,
                total_count=7,
            ),
        "alert_service":
            FakeAlertService(),
        "sync_run_repository":
            FakeSyncRunRepository(),
        "presenter":
            SilentPresenter(),
    }

    return dependencies


def test_happy_path_marks_success_and_returns_summary(
    monkeypatch,
):
    dependencies = build_happy_path(
        monkeypatch
    )

    result = (
        workflow
        .run_synchronization_workflow(
            **dependencies
        )
    )

    assert result.products_seen == 1
    assert result.variants_seen == 1
    assert result.orders_seen == 1
    assert result.line_items_seen == 1
    assert result.new_orders_detected == 1
    assert (
        result.financial_results_processed
        == 1
    )
    assert result.profit_snapshots_stored == 1
    assert result.open_alerts == 2
    assert result.total_alert_history == 7

    assert (
        dependencies[
            "sync_run_repository"
        ].success_calls
        == [
            {
                "run_id": 61,
                "products_seen": 1,
                "variants_seen": 1,
            }
        ]
    )


def test_low_inventory_creates_alert(
    monkeypatch,
):
    dependencies = build_happy_path(
        monkeypatch,
        inventory_quantity=2,
    )

    workflow.run_synchronization_workflow(
        **dependencies
    )

    alert_service = dependencies[
        "alert_service"
    ]

    assert len(
        alert_service.low_inventory_created
    ) == 1

    assert (
        alert_service
        .low_inventory_created[0][
            "threshold"
        ]
        == LOW_INVENTORY_THRESHOLD
    )


def test_healthy_inventory_resolves_existing_alert(
    monkeypatch,
):
    dependencies = build_happy_path(
        monkeypatch,
        inventory_quantity=10,
    )

    workflow.run_synchronization_workflow(
        **dependencies
    )

    assert (
        dependencies[
            "alert_service"
        ].low_inventory_resolved
        == [
            {
                "sku": "SKU-001",
                "variant_id": "variant-001",
            }
        ]
    )


def test_new_order_creates_persistent_alert(
    monkeypatch,
):
    dependencies = build_happy_path(
        monkeypatch,
        new_order=True,
    )

    workflow.run_synchronization_workflow(
        **dependencies
    )

    assert (
        dependencies[
            "alert_service"
        ].new_order_alerts
        == ["order-001"]
    )


def test_missing_cost_creates_missing_cost_alert(
    monkeypatch,
):
    missing_result = (
        complete_financial_result()
    )

    missing_result.update(
        {
            "financial_status":
                "incomplete",
            "snapshots_created":
                0,
            "missing_cost_count":
                1,
            "missing_cost_items":
                [
                    {
                        "sku": "SKU-001",
                        "shopify_variant_id":
                            "variant-001",
                    }
                ],
            "item_results":
                [
                    {
                        "status":
                            "missing_cost",
                        "sku":
                            "SKU-001",
                        "shopify_variant_id":
                            "variant-001",
                    }
                ],
            "summary": None,
        }
    )

    dependencies = build_happy_path(
        monkeypatch,
        financial_result=missing_result,
    )

    workflow.run_synchronization_workflow(
        **dependencies
    )

    assert len(
        dependencies[
            "alert_service"
        ].missing_cost_created
    ) == 1


def test_product_count_mismatch_fails_before_mark_success(
    monkeypatch,
):
    dependencies = build_happy_path(
        monkeypatch
    )

    dependencies[
        "product_repository"
    ].stored_products = []

    try:
        workflow.run_synchronization_workflow(
            **dependencies
        )

    except RuntimeError as exc:
        assert (
            "product record counts do not match"
            in str(exc)
        )

    else:
        raise AssertionError(
            "Expected product verification failure."
        )

    assert (
        dependencies[
            "sync_run_repository"
        ].success_calls
        == []
    )


def test_order_count_mismatch_fails_before_mark_success(
    monkeypatch,
):
    dependencies = build_happy_path(
        monkeypatch
    )

    dependencies[
        "order_repository"
    ].order_count = 0

    try:
        workflow.run_synchronization_workflow(
            **dependencies
        )

    except RuntimeError as exc:
        assert (
            "order record counts do not match"
            in str(exc)
        )

    else:
        raise AssertionError(
            "Expected order verification failure."
        )

    assert (
        dependencies[
            "sync_run_repository"
        ].success_calls
        == []
    )
