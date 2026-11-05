from presentation.terminal_presenter import (
    show_order_retrieval_result,
    show_order_retrieval_started,
    show_product_retrieval_result,
    show_product_retrieval_started,
)


def test_product_retrieval_started_output(
    capsys,
):
    show_product_retrieval_started()

    assert (
        capsys.readouterr().out
        == "Retrieving products...\n"
    )


def test_product_result_preserves_cli_output(
    capsys,
):
    products = [
        {
            "id": "product-001",
            "title": "Automation Test Cap",
            "vendor": "",
            "status": "ACTIVE",
            "variants": {
                "edges": [
                    {
                        "node": {
                            "title": "Default Title",
                            "sku": None,
                            "price": "10.00",
                            "inventoryQuantity": 17,
                        }
                    }
                ]
            },
        }
    ]

    show_product_retrieval_result(
        products
    )

    output = (
        capsys.readouterr().out
    )

    assert "Products found: 1\n" in output
    assert "PRODUCT: Automation Test Cap\n" in output
    assert "Vendor: N/A\n" in output
    assert "Variants: 1\n" in output
    assert "  SKU: NO-SKU\n" in output
    assert "  Price: $10.00\n" in output
    assert "  Inventory: 17\n" in output
    assert (
        "Product retrieval test: SUCCESS\n"
        in output
    )


def test_empty_product_list_still_reports_success(
    capsys,
):
    show_product_retrieval_result([])

    output = capsys.readouterr().out

    assert "Products found: 0\n" in output
    assert (
        output.count("=" * 50)
        == 1
    )
    assert (
        "Product retrieval test: SUCCESS\n"
        in output
    )


def test_order_retrieval_started_output(
    capsys,
):
    show_order_retrieval_started()

    assert (
        capsys.readouterr().out
        == "Retrieving orders...\n"
    )


def test_empty_order_list_preserves_message(
    capsys,
):
    show_order_retrieval_result([])

    output = capsys.readouterr().out

    assert "Orders found: 0\n" in output
    assert "No orders found yet.\n" in output
    assert (
        "Order retrieval test: SUCCESS\n"
        in output
    )


def test_order_result_preserves_status_and_money_output(
    capsys,
):
    orders = [
        {
            "name": "#1004",
            "id": "order-001",
            "createdAt": "2026-10-21T23:03:20Z",
            "updatedAt": "2026-10-21T23:03:20Z",
            "displayFinancialStatus": None,
            "displayFulfillmentStatus": None,
            "totalPriceSet": {
                "shopMoney": {
                    "amount": "25.00",
                    "currencyCode": "USD",
                }
            },
            "lineItems": {
                "edges": []
            },
        }
    ]

    show_order_retrieval_result(
        orders
    )

    output = capsys.readouterr().out

    assert "Orders found: 1\n" in output
    assert "ORDER: #1004\n" in output
    assert "Financial status: N/A\n" in output
    assert "Fulfillment status: N/A\n" in output
    assert "Total: $25.00 USD\n" in output
    assert "Line items: 0\n" in output


def test_order_line_item_preserves_fallbacks(
    capsys,
):
    orders = [
        {
            "name": "#1004",
            "id": "order-001",
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
                            "title": "Custom item",
                            "sku": "",
                            "quantity": 2,
                            "variant": None,
                            "originalUnitPriceSet": {
                                "shopMoney": {
                                    "amount": "12.50",
                                    "currencyCode": None,
                                }
                            },
                        }
                    }
                ]
            },
        }
    ]

    show_order_retrieval_result(
        orders
    )

    output = capsys.readouterr().out

    assert "  Item: Custom item\n" in output
    assert "  SKU: NO-SKU\n" in output
    assert "  Quantity: 2\n" in output
    assert "  Unit price: $12.50 USD\n" in output
    assert "  Variant ID: N/A\n" in output


def test_order_money_defaults_when_shop_money_missing(
    capsys,
):
    orders = [
        {
            "name": "#1005",
            "id": "order-002",
            "createdAt": "created",
            "updatedAt": "updated",
            "displayFinancialStatus": "PENDING",
            "displayFulfillmentStatus": "UNFULFILLED",
            "totalPriceSet": None,
            "lineItems": {
                "edges": []
            },
        }
    ]

    show_order_retrieval_result(
        orders
    )

    output = capsys.readouterr().out

    assert "Total: $0.00 N/A\n" in output
