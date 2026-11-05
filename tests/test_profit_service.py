import pytest

from services.profit_service import ProfitService


@pytest.fixture
def profit_service():
    """
    Return a fresh ProfitService for each test.

    ProfitService is pure business logic, so these tests
    do not need Shopify, SQLite, or network access.
    """

    return ProfitService()


def test_calculate_line_item_profit_single_quantity(
    profit_service,
):
    result = profit_service.calculate_line_item_profit(
        unit_sale_price="10.00",
        unit_cost="4.25",
        quantity=1,
        sale_currency="USD",
        cost_currency="USD",
    )

    assert result == {
        "currency_code": "USD",
        "quantity": 1,
        "unit_sale_price": "10.00",
        "unit_cost": "4.25",
        "line_revenue": "10.00",
        "line_cost": "4.25",
        "estimated_gross_profit": "5.75",
        "gross_margin_percent": "57.50",
    }


def test_calculate_line_item_profit_multiple_quantity(
    profit_service,
):
    result = profit_service.calculate_line_item_profit(
        unit_sale_price="10.00",
        unit_cost="4.25",
        quantity=2,
        sale_currency="USD",
        cost_currency="USD",
    )

    assert result["line_revenue"] == "20.00"
    assert result["line_cost"] == "8.50"
    assert result["estimated_gross_profit"] == "11.50"
    assert result["gross_margin_percent"] == "57.50"


def test_calculate_line_item_profit_normalizes_currency(
    profit_service,
):
    result = profit_service.calculate_line_item_profit(
        unit_sale_price="10.00",
        unit_cost="4.25",
        quantity=1,
        sale_currency="usd",
        cost_currency=" usd ",
    )

    assert result["currency_code"] == "USD"


def test_calculate_line_item_profit_rejects_currency_mismatch(
    profit_service,
):
    with pytest.raises(
        ValueError,
        match=(
            "Cannot calculate profit across different "
            "currencies without currency conversion"
        ),
    ):
        profit_service.calculate_line_item_profit(
            unit_sale_price="10.00",
            unit_cost="4.25",
            quantity=1,
            sale_currency="USD",
            cost_currency="COP",
        )


def test_calculate_line_item_profit_rejects_invalid_price(
    profit_service,
):
    with pytest.raises(
        ValueError,
        match=(
            "unit_sale_price must be a valid "
            "decimal number"
        ),
    ):
        profit_service.calculate_line_item_profit(
            unit_sale_price="hello",
            unit_cost="4.25",
            quantity=1,
            sale_currency="USD",
            cost_currency="USD",
        )


def test_calculate_line_item_profit_rejects_negative_cost(
    profit_service,
):
    with pytest.raises(
        ValueError,
        match="unit_cost cannot be negative",
    ):
        profit_service.calculate_line_item_profit(
            unit_sale_price="10.00",
            unit_cost="-1.00",
            quantity=1,
            sale_currency="USD",
            cost_currency="USD",
        )


@pytest.mark.parametrize(
    "invalid_quantity",
    [
        True,
        1.5,
        "1",
        -1,
    ],
)
def test_calculate_line_item_profit_rejects_invalid_quantity(
    profit_service,
    invalid_quantity,
):
    with pytest.raises(ValueError):
        profit_service.calculate_line_item_profit(
            unit_sale_price="10.00",
            unit_cost="4.25",
            quantity=invalid_quantity,
            sale_currency="USD",
            cost_currency="USD",
        )


def test_zero_revenue_returns_no_margin(
    profit_service,
):
    result = profit_service.calculate_line_item_profit(
        unit_sale_price="0.00",
        unit_cost="4.25",
        quantity=1,
        sale_currency="USD",
        cost_currency="USD",
    )

    assert result["line_revenue"] == "0.00"
    assert result["line_cost"] == "4.25"
    assert result["estimated_gross_profit"] == "-4.25"
    assert result["gross_margin_percent"] is None


def test_calculate_order_summary_combines_snapshots(
    profit_service,
):
    snapshots = [
        {
            "currency_code": "USD",
            "quantity": 1,
            "line_revenue": "10.00",
            "line_cost": "4.25",
            "estimated_gross_profit": "5.75",
        },
        {
            "currency_code": "USD",
            "quantity": 2,
            "line_revenue": "20.00",
            "line_cost": "8.50",
            "estimated_gross_profit": "11.50",
        },
    ]

    result = profit_service.calculate_order_summary(
        snapshots
    )

    assert result == {
        "currency_code": "USD",
        "line_items_count": 2,
        "total_quantity": 3,
        "merchandise_revenue": "30.00",
        "product_cost": "12.75",
        "estimated_gross_profit": "17.25",
        "gross_margin_percent": "57.50",
    }


def test_calculate_order_summary_uses_weighted_margin(
    profit_service,
):
    snapshots = [
        {
            "currency_code": "USD",
            "quantity": 1,
            "line_revenue": "10.00",
            "line_cost": "4.00",
            "estimated_gross_profit": "6.00",
        },
        {
            "currency_code": "USD",
            "quantity": 2,
            "line_revenue": "25.00",
            "line_cost": "13.50",
            "estimated_gross_profit": "11.50",
        },
    ]

    result = profit_service.calculate_order_summary(
        snapshots
    )

    assert result["merchandise_revenue"] == "35.00"
    assert result["product_cost"] == "17.50"
    assert result["estimated_gross_profit"] == "17.50"
    assert result["gross_margin_percent"] == "50.00"


def test_calculate_order_summary_rejects_empty_list(
    profit_service,
):
    with pytest.raises(
        ValueError,
        match="At least one profit snapshot is required",
    ):
        profit_service.calculate_order_summary([])


def test_calculate_order_summary_rejects_mixed_currencies(
    profit_service,
):
    snapshots = [
        {
            "currency_code": "USD",
            "quantity": 1,
            "line_revenue": "10.00",
            "line_cost": "4.00",
            "estimated_gross_profit": "6.00",
        },
        {
            "currency_code": "COP",
            "quantity": 1,
            "line_revenue": "20000.00",
            "line_cost": "10000.00",
            "estimated_gross_profit": "10000.00",
        },
    ]

    with pytest.raises(
        ValueError,
        match=(
            "Cannot summarize snapshots with "
            "different currencies"
        ),
    ):
        profit_service.calculate_order_summary(
            snapshots
        )


def test_calculate_order_summary_zero_revenue_returns_no_margin(
    profit_service,
):
    snapshots = [
        {
            "currency_code": "USD",
            "quantity": 1,
            "line_revenue": "0.00",
            "line_cost": "4.25",
            "estimated_gross_profit": "-4.25",
        },
    ]

    result = profit_service.calculate_order_summary(
        snapshots
    )

    assert result["merchandise_revenue"] == "0.00"
    assert result["product_cost"] == "4.25"
    assert result["estimated_gross_profit"] == "-4.25"
    assert result["gross_margin_percent"] is None
