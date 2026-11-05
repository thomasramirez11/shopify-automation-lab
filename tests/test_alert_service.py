import pytest

from services.alert_service import AlertService


class FakeAlertRepository:
    """
    Small in-memory test double.

    It records what AlertService asks the repository to do,
    without using SQLite.
    """

    def __init__(self):
        self.created_alerts = []
        self.resolved_keys = []
        self.resolve_result = True

    def create_or_touch_alert(self, **kwargs):
        self.created_alerts.append(kwargs)

        return {
            "id": len(self.created_alerts),
            "status": "open",
            "occurrence_count": 1,
            **kwargs,
        }

    def resolve_alert(self, dedupe_key):
        self.resolved_keys.append(dedupe_key)
        return self.resolve_result


@pytest.fixture
def fake_repository():
    return FakeAlertRepository()


@pytest.fixture
def alert_service(fake_repository):
    return AlertService(
        alert_repository=fake_repository,
    )


def test_new_order_alert_uses_info_severity_and_stable_key(
    alert_service,
    fake_repository,
):
    order = {
        "id": "gid://shopify/Order/1001",
        "name": "#1001",
        "totalPriceSet": {
            "shopMoney": {
                "amount": "25.00",
                "currencyCode": "USD",
            }
        },
        "lineItems": {
            "edges": [
                {"node": {"id": "line-001"}},
                {"node": {"id": "line-002"}},
            ]
        },
    }

    result = (
        alert_service.create_new_order_alert(
            order
        )
    )

    created = fake_repository.created_alerts[0]

    assert created["alert_type"] == "new_order"
    assert created["severity"] == "info"

    assert (
        created["dedupe_key"]
        == "new_order:gid://shopify/Order/1001"
    )

    assert (
        created["title"]
        == "New Shopify order #1001"
    )

    assert "25.00 USD" in created["message"]
    assert "Line items: 2" in created["message"]

    assert created["entity_type"] == "order"

    assert (
        created["entity_id"]
        == "gid://shopify/Order/1001"
    )

    assert result["alert_type"] == "new_order"


def test_new_order_alert_requires_order_id(
    alert_service,
):
    with pytest.raises(
        ValueError,
        match=(
            "New-order alert requires "
            "a Shopify order ID"
        ),
    ):
        alert_service.create_new_order_alert(
            {
                "name": "#1001",
            }
        )


def test_new_order_alert_requires_order_name(
    alert_service,
):
    with pytest.raises(
        ValueError,
        match=(
            "New-order alert requires "
            "a Shopify order name"
        ),
    ):
        alert_service.create_new_order_alert(
            {
                "id": "order-001",
            }
        )


def test_new_order_alert_uses_na_for_missing_money(
    alert_service,
    fake_repository,
):
    alert_service.create_new_order_alert(
        {
            "id": "order-001",
            "name": "#1001",
            "lineItems": {
                "edges": [],
            },
        }
    )

    created = fake_repository.created_alerts[0]

    assert "Total: N/A N/A" in created["message"]


def test_missing_cost_alert_prefers_variant_id_for_dedupe(
    alert_service,
    fake_repository,
):
    alert_service.create_missing_cost_alert(
        order_name="#1002",
        missing_item={
            "sku": "AUTO-SHIRT-L",
            "shopify_variant_id": "variant-001",
        },
    )

    created = fake_repository.created_alerts[0]

    assert created["alert_type"] == "missing_cost"
    assert created["severity"] == "warning"

    assert (
        created["dedupe_key"]
        == "missing_cost:variant-001"
    )

    assert created["entity_type"] == "variant"
    assert created["entity_id"] == "variant-001"

    assert (
        created["title"]
        == "Missing cost for AUTO-SHIRT-L"
    )

    assert "#1002" in created["message"]


def test_missing_cost_alert_uses_sku_as_fallback_key(
    alert_service,
    fake_repository,
):
    alert_service.create_missing_cost_alert(
        order_name="#1002",
        missing_item={
            "sku": "AUTO-SHIRT-L",
            "shopify_variant_id": None,
        },
    )

    created = fake_repository.created_alerts[0]

    assert (
        created["dedupe_key"]
        == "missing_cost:sku:AUTO-SHIRT-L"
    )

    assert created["entity_id"] == "AUTO-SHIRT-L"


def test_missing_cost_alert_requires_variant_id_or_sku(
    alert_service,
):
    with pytest.raises(
        ValueError,
        match=(
            "Cannot build missing-cost alert "
            "without a variant ID or SKU"
        ),
    ):
        alert_service.create_missing_cost_alert(
            order_name="#1002",
            missing_item={
                "sku": None,
                "shopify_variant_id": None,
            },
        )


def test_resolve_missing_cost_alert_uses_variant_key(
    alert_service,
    fake_repository,
):
    resolved = (
        alert_service.resolve_missing_cost_alert(
            sku="AUTO-SHIRT-L",
            variant_id="variant-001",
        )
    )

    assert resolved is True

    assert fake_repository.resolved_keys == [
        "missing_cost:variant-001"
    ]


def test_resolve_missing_cost_alert_uses_sku_fallback(
    alert_service,
    fake_repository,
):
    alert_service.resolve_missing_cost_alert(
        sku="AUTO-SHIRT-L",
        variant_id=None,
    )

    assert fake_repository.resolved_keys == [
        "missing_cost:sku:AUTO-SHIRT-L"
    ]


def test_resolve_missing_cost_alert_returns_repository_result(
    alert_service,
    fake_repository,
):
    fake_repository.resolve_result = False

    resolved = (
        alert_service.resolve_missing_cost_alert(
            sku="AUTO-SHIRT-L",
            variant_id=None,
        )
    )

    assert resolved is False


def test_low_inventory_positive_stock_is_warning(
    alert_service,
    fake_repository,
):
    alert_service.create_low_inventory_alert(
        product_title="Automation Test Cap",
        variant={
            "id": "variant-001",
            "sku": "AUTO-CAP-001",
            "title": "Default Title",
            "inventoryQuantity": 2,
        },
        threshold=5,
    )

    created = fake_repository.created_alerts[0]

    assert created["alert_type"] == "low_inventory"
    assert created["severity"] == "warning"

    assert (
        created["dedupe_key"]
        == "low_inventory:variant-001"
    )

    assert (
        created["title"]
        == "Low inventory for AUTO-CAP-001"
    )

    assert "2 units in stock" in created["message"]
    assert "threshold is 5" in created["message"]


@pytest.mark.parametrize(
    "inventory_quantity",
    [
        0,
        -1,
    ],
)
def test_zero_or_negative_inventory_is_critical(
    alert_service,
    fake_repository,
    inventory_quantity,
):
    alert_service.create_low_inventory_alert(
        product_title="Automation Test Cap",
        variant={
            "id": "variant-001",
            "sku": "AUTO-CAP-001",
            "title": "Default Title",
            "inventoryQuantity":
                inventory_quantity,
        },
        threshold=5,
    )

    created = fake_repository.created_alerts[0]

    assert created["severity"] == "critical"


def test_low_inventory_prefers_variant_id_for_dedupe(
    alert_service,
    fake_repository,
):
    alert_service.create_low_inventory_alert(
        product_title="Product",
        variant={
            "id": "variant-001",
            "sku": "SKU-001",
            "title": "Variant",
            "inventoryQuantity": 4,
        },
        threshold=5,
    )

    created = fake_repository.created_alerts[0]

    assert (
        created["dedupe_key"]
        == "low_inventory:variant-001"
    )


def test_low_inventory_uses_sku_fallback_when_variant_id_missing(
    alert_service,
    fake_repository,
):
    alert_service.create_low_inventory_alert(
        product_title="Product",
        variant={
            "id": None,
            "sku": "SKU-001",
            "title": "Variant",
            "inventoryQuantity": 4,
        },
        threshold=5,
    )

    created = fake_repository.created_alerts[0]

    assert (
        created["dedupe_key"]
        == "low_inventory:sku:SKU-001"
    )

    assert created["entity_id"] == "SKU-001"


def test_low_inventory_without_sku_uses_product_and_variant_title(
    alert_service,
    fake_repository,
):
    alert_service.create_low_inventory_alert(
        product_title="Nike shoes test",
        variant={
            "id": "variant-001",
            "sku": None,
            "title": "shoe",
            "inventoryQuantity": 4,
        },
        threshold=5,
    )

    created = fake_repository.created_alerts[0]

    assert (
        created["title"]
        == "Low inventory for Nike shoes test / shoe"
    )

    assert (
        "Nike shoes test / shoe has 4 units in stock"
        in created["message"]
    )


@pytest.mark.parametrize(
    "invalid_inventory",
    [
        True,
        False,
        "2",
        2.5,
        None,
    ],
)
def test_low_inventory_requires_integer_inventory(
    alert_service,
    invalid_inventory,
):
    with pytest.raises(
        ValueError,
        match=(
            "Low-inventory alert requires "
            "an integer inventory quantity"
        ),
    ):
        alert_service.create_low_inventory_alert(
            product_title="Product",
            variant={
                "id": "variant-001",
                "sku": "SKU-001",
                "title": "Variant",
                "inventoryQuantity":
                    invalid_inventory,
            },
            threshold=5,
        )


@pytest.mark.parametrize(
    "invalid_threshold",
    [
        True,
        False,
        "5",
        5.0,
        None,
    ],
)
def test_low_inventory_threshold_must_be_integer(
    alert_service,
    invalid_threshold,
):
    with pytest.raises(
        ValueError,
        match=(
            "Low-inventory threshold must "
            "be an integer"
        ),
    ):
        alert_service.create_low_inventory_alert(
            product_title="Product",
            variant={
                "id": "variant-001",
                "sku": "SKU-001",
                "title": "Variant",
                "inventoryQuantity": 2,
            },
            threshold=invalid_threshold,
        )


def test_low_inventory_threshold_cannot_be_negative(
    alert_service,
):
    with pytest.raises(
        ValueError,
        match=(
            "Low-inventory threshold "
            "cannot be negative"
        ),
    ):
        alert_service.create_low_inventory_alert(
            product_title="Product",
            variant={
                "id": "variant-001",
                "sku": "SKU-001",
                "title": "Variant",
                "inventoryQuantity": 2,
            },
            threshold=-1,
        )


def test_low_inventory_requires_stable_variant_or_sku_key(
    alert_service,
):
    with pytest.raises(
        ValueError,
        match=(
            "Cannot build low-inventory alert "
            "without a variant ID or SKU"
        ),
    ):
        alert_service.create_low_inventory_alert(
            product_title="Product",
            variant={
                "id": None,
                "sku": None,
                "title": "Variant",
                "inventoryQuantity": 2,
            },
            threshold=5,
        )


def test_resolve_low_inventory_alert_uses_variant_key(
    alert_service,
    fake_repository,
):
    resolved = (
        alert_service.resolve_low_inventory_alert(
            sku="SKU-001",
            variant_id="variant-001",
        )
    )

    assert resolved is True

    assert fake_repository.resolved_keys == [
        "low_inventory:variant-001"
    ]


def test_resolve_low_inventory_alert_uses_sku_fallback(
    alert_service,
    fake_repository,
):
    alert_service.resolve_low_inventory_alert(
        sku="SKU-001",
        variant_id=None,
    )

    assert fake_repository.resolved_keys == [
        "low_inventory:sku:SKU-001"
    ]


def test_resolve_low_inventory_alert_returns_repository_result(
    alert_service,
    fake_repository,
):
    fake_repository.resolve_result = False

    resolved = (
        alert_service.resolve_low_inventory_alert(
            sku="SKU-001",
            variant_id=None,
        )
    )

    assert resolved is False


def test_resolve_low_inventory_requires_stable_key(
    alert_service,
):
    with pytest.raises(
        ValueError,
        match=(
            "Cannot build low-inventory alert "
            "without a variant ID or SKU"
        ),
    ):
        alert_service.resolve_low_inventory_alert(
            sku=None,
            variant_id=None,
        )
