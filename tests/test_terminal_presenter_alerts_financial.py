from presentation.terminal_presenter import (
    show_active_low_inventory_alert,
    show_alert_database_status,
    show_financial_analysis_started,
    show_financial_processing_count,
    show_financial_results,
    show_financial_snapshot_status,
    show_low_inventory_processing_started,
    show_low_inventory_summary,
    show_missing_cost_alert_summary,
    show_new_order_alert_created,
    show_new_order_alert_processing_started,
    show_new_order_alert_summary,
    show_new_order_detection,
    show_resolved_low_inventory_alert,
)


def test_low_inventory_start_preserves_threshold(
    capsys,
):
    show_low_inventory_processing_started(5)

    output = capsys.readouterr().out

    assert "Low-inventory alert processing\n" in output
    assert "Configured threshold: 5\n" in output


def test_active_low_inventory_alert_output(
    capsys,
):
    show_active_low_inventory_alert(
        {
            "id": 10,
            "title": "Low inventory for AUTO-shirt-L",
            "occurrence_count": 3,
        }
    )

    output = capsys.readouterr().out

    assert (
        "Active low-inventory alert: "
        "Low inventory for AUTO-shirt-L "
        "(Alert ID: 10, Occurrences: 3)\n"
        in output
    )


def test_resolved_low_inventory_alert_uses_no_sku_fallback(
    capsys,
):
    show_resolved_low_inventory_alert(
        sku=None,
        inventory_quantity=10,
    )

    assert (
        "Resolved low-inventory alert for SKU: "
        "NO-SKU (Inventory: 10)\n"
        == capsys.readouterr().out
    )


def test_low_inventory_summary_reports_zero_active_state(
    capsys,
):
    show_low_inventory_summary(
        inventory_variants_checked=4,
        untracked_variants_skipped=0,
        processed_count=0,
        resolved_count=1,
    )

    output = capsys.readouterr().out

    assert (
        "No active low-inventory conditions detected.\n"
        in output
    )
    assert "Inventory variants checked: 4\n" in output
    assert "Low-inventory alerts resolved: 1\n" in output


def test_new_order_detection_preserves_order_summary(
    capsys,
):
    show_new_order_detection(
        [
            {
                "name": "#1004",
                "totalPriceSet": {
                    "shopMoney": {
                        "amount": "29.97",
                        "currencyCode": "USD",
                    }
                },
                "lineItems": {
                    "edges": [
                        {"node": {}},
                    ]
                },
            }
        ]
    )

    output = capsys.readouterr().out

    assert "New orders detected: 1\n" in output
    assert "*** NEW ORDER DETECTED ***\n" in output
    assert "Order: #1004\n" in output
    assert "Total: $29.97 USD\n" in output
    assert "Line items: 1\n" in output


def test_new_order_detection_empty_state(
    capsys,
):
    show_new_order_detection([])

    output = capsys.readouterr().out

    assert "New orders detected: 0\n" in output
    assert "No new orders detected.\n" in output


def test_new_order_alert_output(
    capsys,
):
    show_new_order_alert_processing_started()

    show_new_order_alert_created(
        order_name="#1004",
        alert_id=6,
    )

    show_new_order_alert_summary(1)

    output = capsys.readouterr().out

    assert "New-order alert processing\n" in output
    assert (
        "Alert created for order #1004 "
        "(Alert ID: 6)\n"
        in output
    )
    assert "New-order alerts processed: 1\n" in output


def test_new_order_alert_zero_state(
    capsys,
):
    show_new_order_alert_summary(0)

    output = capsys.readouterr().out

    assert "No new-order alerts created.\n" in output
    assert "New-order alerts processed: 0\n" in output


def test_financial_processing_headers_and_count(
    capsys,
):
    show_financial_analysis_started()
    show_financial_processing_count(4)

    output = capsys.readouterr().out

    assert "Financial analysis\n" in output
    assert "Orders financially processed: 4\n" in output


def test_missing_cost_summary_preserves_active_and_resolved_states(
    capsys,
):
    show_missing_cost_alert_summary(
        processed_alerts=[
            {
                "id": 7,
                "title": "Missing cost for NO-SKU",
                "occurrence_count": 1,
            }
        ],
        resolved_items=[
            {
                "sku": None,
            }
        ],
    )

    output = capsys.readouterr().out

    assert (
        "Active missing-cost alert: "
        "Missing cost for NO-SKU "
        "(Alert ID: 7, Occurrences: 1)\n"
        in output
    )
    assert (
        "Resolved missing-cost alert for SKU: NO-SKU\n"
        in output
    )
    assert "Missing-cost alerts processed: 1\n" in output
    assert "Missing-cost alerts resolved: 1\n" in output


def test_financial_result_complete_summary(
    capsys,
):
    show_financial_results(
        [
            {
                "order_name": "#1004",
                "financial_status": "complete",
                "line_items_seen": 1,
                "snapshots_created": 1,
                "existing_snapshots": 0,
                "missing_cost_count": 0,
                "missing_cost_items": [],
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
        ]
    )

    output = capsys.readouterr().out

    assert "Order: #1004\n" in output
    assert "Financial status: COMPLETE\n" in output
    assert "Merchandise revenue: 25.00 USD\n" in output
    assert "Estimated gross profit: 15.00 USD\n" in output
    assert "Gross margin: 60.00%\n" in output


def test_financial_result_missing_cost_state(
    capsys,
):
    show_financial_results(
        [
            {
                "order_name": "#1004",
                "financial_status": "incomplete",
                "line_items_seen": 1,
                "snapshots_created": 0,
                "existing_snapshots": 0,
                "missing_cost_count": 1,
                "missing_cost_items": [
                    {
                        "sku": None,
                        "shopify_variant_id": "variant-001",
                    }
                ],
                "summary": None,
            }
        ]
    )

    output = capsys.readouterr().out

    assert "Missing cost configuration\n" in output
    assert "SKU: NO-SKU\n" in output
    assert "Variant ID: variant-001\n" in output
    assert (
        "Profit summary unavailable until all product costs "
        "are configured.\n"
        in output
    )


def test_snapshot_and_alert_database_status(
    capsys,
):
    show_financial_snapshot_status(4)

    show_alert_database_status(
        open_alert_count=5,
        total_alert_count=7,
    )

    output = capsys.readouterr().out

    assert "Profit snapshots stored: 4\n" in output
    assert "Open alerts: 5\n" in output
    assert "Total alert history: 7\n" in output
