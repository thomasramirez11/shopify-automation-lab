from application.inventory_alert_workflow import (
    InventoryAlertResult,
    process_inventory_alerts,
)
from application.product_sync_workflow import (
    ProductSyncState,
)


class RecordingPresenter:
    def __init__(self):
        self.calls = []

    def show_low_inventory_processing_started(
        self,
        threshold,
    ):
        self.calls.append(
            (
                "started",
                threshold,
            )
        )

    def show_active_low_inventory_alert(
        self,
        alert,
    ):
        self.calls.append(
            (
                "active",
                alert,
            )
        )

    def show_resolved_low_inventory_alert(
        self,
        *,
        sku,
        inventory_quantity,
    ):
        self.calls.append(
            (
                "resolved",
                {
                    "sku": sku,
                    "inventory_quantity": (
                        inventory_quantity
                    ),
                },
            )
        )

    def show_low_inventory_summary(
        self,
        **kwargs,
    ):
        self.calls.append(
            (
                "summary",
                kwargs,
            )
        )


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

    def create_low_inventory_alert(
        self,
        *,
        product_title,
        variant,
        threshold,
    ):
        self.created.append(
            {
                "product_title": (
                    product_title
                ),
                "variant": variant,
                "threshold": threshold,
            }
        )

        return {
            "id": 10,
            "title": "Low inventory",
            "occurrence_count": 1,
        }

    def resolve_low_inventory_alert(
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


def make_variant(
    *,
    variant_id="variant-1",
    sku="SKU-1",
    inventory_quantity=10,
    tracked=True,
):
    return {
        "id": variant_id,
        "title": "Default Title",
        "sku": sku,
        "inventoryQuantity": (
            inventory_quantity
        ),
        "inventoryItem": {
            "tracked": tracked,
        },
    }


def make_product(
    *,
    title="Test product",
    variants=None,
):
    return {
        "id": "product-1",
        "title": title,
        "variants": {
            "edges": [
                {
                    "node": variant,
                }
                for variant in (
                    variants or []
                )
            ]
        },
    }


def run_case(
    *,
    products,
    threshold=5,
    resolve_result=True,
):
    presenter = RecordingPresenter()

    alert_service = FakeAlertService(
        resolve_result=resolve_result,
    )

    result = process_inventory_alerts(
        product_state=(
            ProductSyncState(
                products=products,
            )
        ),
        alert_service=alert_service,
        presenter=presenter,
        threshold=threshold,
    )

    return (
        result,
        alert_service,
        presenter,
    )


def test_low_inventory_creates_alert():
    variant = make_variant(
        inventory_quantity=2,
    )

    result, service, presenter = (
        run_case(
            products=[
                make_product(
                    variants=[variant],
                )
            ]
        )
    )

    assert isinstance(
        result,
        InventoryAlertResult,
    )

    assert result.variants_checked == 1
    assert result.alerts_processed == 1
    assert result.alerts_resolved == 0

    assert len(service.created) == 1

    assert (
        service.created[0]["threshold"]
        == 5
    )

    assert presenter.calls[1][0] == "active"


def test_inventory_equal_to_threshold_is_low():
    result, service, _ = run_case(
        products=[
            make_product(
                variants=[
                    make_variant(
                        inventory_quantity=5,
                    )
                ],
            )
        ],
        threshold=5,
    )

    assert result.alerts_processed == 1
    assert len(service.created) == 1


def test_healthy_inventory_attempts_resolution():
    result, service, presenter = (
        run_case(
            products=[
                make_product(
                    variants=[
                        make_variant(
                            inventory_quantity=10,
                        )
                    ],
                )
            ]
        )
    )

    assert result.variants_checked == 1
    assert result.alerts_processed == 0
    assert result.alerts_resolved == 1

    assert service.resolved == [
        {
            "sku": "SKU-1",
            "variant_id": "variant-1",
        }
    ]

    assert presenter.calls[1][0] == "resolved"


def test_untracked_inventory_is_skipped():
    result, service, presenter = (
        run_case(
            products=[
                make_product(
                    variants=[
                        make_variant(
                            inventory_quantity=1,
                            tracked=False,
                        )
                    ],
                )
            ]
        )
    )

    assert result.variants_checked == 0
    assert (
        result.untracked_variants_skipped
        == 1
    )

    assert service.created == []
    assert service.resolved == []

    assert presenter.calls[-1] == (
        "summary",
        {
            "inventory_variants_checked": 0,
            "untracked_variants_skipped": 1,
            "processed_count": 0,
            "resolved_count": 0,
        },
    )


def test_missing_inventory_quantity_is_skipped():
    result, service, _ = run_case(
        products=[
            make_product(
                variants=[
                    make_variant(
                        inventory_quantity=None,
                    )
                ],
            )
        ]
    )

    assert result.variants_checked == 0
    assert result.alerts_processed == 0
    assert result.alerts_resolved == 0
    assert service.created == []
    assert service.resolved == []


def test_variant_without_sku_can_resolve_by_variant_id():
    result, service, presenter = (
        run_case(
            products=[
                make_product(
                    variants=[
                        make_variant(
                            sku=None,
                            variant_id="variant-9",
                            inventory_quantity=10,
                        )
                    ],
                )
            ]
        )
    )

    assert result.alerts_resolved == 1

    assert service.resolved == [
        {
            "sku": None,
            "variant_id": "variant-9",
        }
    ]

    assert presenter.calls[1][1] == {
        "sku": None,
        "inventory_quantity": 10,
    }


def test_variant_without_stable_key_does_not_attempt_resolution():
    result, service, _ = run_case(
        products=[
            make_product(
                variants=[
                    make_variant(
                        sku=None,
                        variant_id=None,
                        inventory_quantity=10,
                    )
                ],
            )
        ]
    )

    assert result.variants_checked == 1
    assert result.alerts_resolved == 0
    assert service.resolved == []


def test_unsuccessful_resolution_is_not_counted():
    result, service, presenter = (
        run_case(
            products=[
                make_product(
                    variants=[
                        make_variant(
                            inventory_quantity=10,
                        )
                    ],
                )
            ],
            resolve_result=False,
        )
    )

    assert len(service.resolved) == 1
    assert result.alerts_resolved == 0

    call_names = [
        call[0]
        for call in presenter.calls
    ]

    assert "resolved" not in call_names


def test_multiple_products_produce_aggregate_summary():
    products = [
        make_product(
            title="Product A",
            variants=[
                make_variant(
                    variant_id="a-1",
                    sku="A-1",
                    inventory_quantity=2,
                ),
                make_variant(
                    variant_id="a-2",
                    sku="A-2",
                    inventory_quantity=10,
                ),
            ],
        ),
        make_product(
            title="Product B",
            variants=[
                make_variant(
                    variant_id="b-1",
                    sku="B-1",
                    inventory_quantity=1,
                    tracked=False,
                ),
                make_variant(
                    variant_id="b-2",
                    sku="B-2",
                    inventory_quantity=None,
                ),
            ],
        ),
    ]

    result, _, presenter = run_case(
        products=products,
    )

    assert result == InventoryAlertResult(
        variants_checked=2,
        untracked_variants_skipped=1,
        alerts_processed=1,
        alerts_resolved=1,
    )

    assert presenter.calls[-1] == (
        "summary",
        {
            "inventory_variants_checked": 2,
            "untracked_variants_skipped": 1,
            "processed_count": 1,
            "resolved_count": 1,
        },
    )
