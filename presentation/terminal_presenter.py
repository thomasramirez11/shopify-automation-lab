from __future__ import annotations


def show_product_retrieval_started() -> None:
    """
    Display the start of Shopify product retrieval.
    """

    print("Retrieving products...")


def show_product_retrieval_result(
    products: list[dict],
) -> None:
    """
    Display Shopify product data exactly as the synchronization
    command-line workflow expects it.

    This function is presentation-only:
        - it does not call Shopify
        - it does not write to SQLite
        - it does not mutate product data
    """

    print(
        f"Products found: {len(products)}"
    )
    print()

    for product in products:
        print("=" * 50)

        print(
            f"PRODUCT: {product['title']}"
        )

        print(
            f"ID: {product['id']}"
        )

        print(
            "Vendor: "
            f"{product['vendor'] or 'N/A'}"
        )

        print(
            f"Status: {product['status']}"
        )

        variant_edges = (
            product["variants"]["edges"]
        )

        print(
            f"Variants: {len(variant_edges)}"
        )
        print()

        for variant_edge in variant_edges:
            variant = variant_edge["node"]

            print(
                f"  Variant: {variant['title']}"
            )

            print(
                "  SKU: "
                f"{variant['sku'] or 'NO-SKU'}"
            )

            print(
                "  Price: "
                f"${variant['price']}"
            )

            print(
                "  Inventory: "
                f"{variant['inventoryQuantity']}"
            )

            print()

    print("=" * 50)
    print(
        "Product retrieval test: SUCCESS"
    )
    print()


def show_order_retrieval_started() -> None:
    """
    Display the start of Shopify order retrieval.
    """

    print("Retrieving orders...")


def show_order_retrieval_result(
    orders: list[dict],
) -> None:
    """
    Display Shopify order data exactly as the synchronization
    command-line workflow expects it.

    This function is presentation-only and intentionally contains
    the terminal-specific fallback labels used by the V1 CLI.
    """

    print(
        f"Orders found: {len(orders)}"
    )
    print()

    if not orders:
        print("No orders found yet.")
        print()

    for order in orders:
        print("=" * 50)

        total_price_set = (
            order.get("totalPriceSet")
            or {}
        )

        shop_money = (
            total_price_set.get("shopMoney")
            or {}
        )

        total_amount = (
            shop_money.get("amount")
            or "0.00"
        )

        currency_code = (
            shop_money.get("currencyCode")
            or "N/A"
        )

        financial_status = (
            order.get(
                "displayFinancialStatus"
            )
            or "N/A"
        )

        fulfillment_status = (
            order.get(
                "displayFulfillmentStatus"
            )
            or "N/A"
        )

        print(
            f"ORDER: {order['name']}"
        )

        print(
            f"ID: {order['id']}"
        )

        print(
            "Created: "
            f"{order['createdAt']}"
        )

        print(
            "Updated: "
            f"{order['updatedAt']}"
        )

        print(
            "Financial status: "
            f"{financial_status}"
        )

        print(
            "Fulfillment status: "
            f"{fulfillment_status}"
        )

        print(
            f"Total: ${total_amount} "
            f"{currency_code}"
        )

        line_item_edges = (
            order
            .get("lineItems", {})
            .get("edges", [])
        )

        print(
            "Line items: "
            f"{len(line_item_edges)}"
        )

        print()

        for line_item_edge in (
            line_item_edges
        ):
            line_item = (
                line_item_edge["node"]
            )

            variant = (
                line_item.get("variant")
                or {}
            )

            unit_price_set = (
                line_item.get(
                    "originalUnitPriceSet"
                )
                or {}
            )

            unit_shop_money = (
                unit_price_set.get(
                    "shopMoney"
                )
                or {}
            )

            unit_amount = (
                unit_shop_money.get(
                    "amount"
                )
                or "0.00"
            )

            unit_currency = (
                unit_shop_money.get(
                    "currencyCode"
                )
                or currency_code
            )

            print(
                "  Item: "
                f"{line_item['title']}"
            )

            print(
                "  SKU: "
                f"{line_item.get('sku') or 'NO-SKU'}"
            )

            print(
                "  Quantity: "
                f"{line_item['quantity']}"
            )

            print(
                "  Unit price: "
                f"${unit_amount} "
                f"{unit_currency}"
            )

            print(
                "  Variant ID: "
                f"{variant.get('id') or 'N/A'}"
            )

            print()

    print("=" * 50)
    print(
        "Order retrieval test: SUCCESS"
    )
    print()

def show_low_inventory_processing_started(
    threshold: int,
) -> None:
    """
    Display low-inventory alert processing start state.
    """

    print("Low-inventory alert processing")
    print("------------------------------")
    print(
        f"Configured threshold: {threshold}"
    )


def show_active_low_inventory_alert(
    alert: dict,
) -> None:
    """
    Display one active low-inventory alert.
    """

    print(
        "Active low-inventory alert: "
        f"{alert['title']} "
        f"(Alert ID: {alert['id']}, "
        f"Occurrences: "
        f"{alert['occurrence_count']})"
    )


def show_resolved_low_inventory_alert(
    *,
    sku: str | None,
    inventory_quantity: int,
) -> None:
    """
    Display one resolved low-inventory alert.
    """

    print(
        "Resolved low-inventory "
        "alert for SKU: "
        f"{sku or 'NO-SKU'} "
        f"(Inventory: "
        f"{inventory_quantity})"
    )


def show_low_inventory_summary(
    *,
    inventory_variants_checked: int,
    untracked_variants_skipped: int,
    processed_count: int,
    resolved_count: int,
) -> None:
    """
    Display the low-inventory processing summary.
    """

    if processed_count == 0:
        print(
            "No active low-inventory "
            "conditions detected."
        )

    print(
        "Inventory variants checked: "
        f"{inventory_variants_checked}"
    )

    print(
        "Untracked variants skipped: "
        f"{untracked_variants_skipped}"
    )

    print(
        "Low-inventory alerts processed: "
        f"{processed_count}"
    )

    print(
        "Low-inventory alerts resolved: "
        f"{resolved_count}"
    )

    print()


def show_new_order_detection(
    new_orders: list[dict],
) -> None:
    """
    Display newly detected Shopify orders.
    """

    print("New order detection")
    print("-------------------")

    print(
        "New orders detected: "
        f"{len(new_orders)}"
    )

    if not new_orders:
        print("No new orders detected.")

    for order in new_orders:
        total_price_set = (
            order.get("totalPriceSet")
            or {}
        )

        shop_money = (
            total_price_set.get("shopMoney")
            or {}
        )

        total_amount = (
            shop_money.get("amount")
            or "0.00"
        )

        currency_code = (
            shop_money.get("currencyCode")
            or "N/A"
        )

        print()
        print("*** NEW ORDER DETECTED ***")
        print(
            f"Order: {order['name']}"
        )

        print(
            f"Total: ${total_amount} "
            f"{currency_code}"
        )

        line_item_edges = (
            order
            .get("lineItems", {})
            .get("edges", [])
        )

        print(
            "Line items: "
            f"{len(line_item_edges)}"
        )

    print()


def show_new_order_alert_processing_started() -> None:
    """
    Display the start of new-order alert processing.
    """

    print("New-order alert processing")
    print("--------------------------")


def show_new_order_alert_created(
    *,
    order_name: str,
    alert_id: int,
) -> None:
    """
    Display one newly created order alert.
    """

    print(
        "Alert created for order "
        f"{order_name} "
        f"(Alert ID: {alert_id})"
    )


def show_new_order_alert_summary(
    processed_count: int,
) -> None:
    """
    Display new-order alert processing totals.
    """

    if processed_count == 0:
        print(
            "No new-order alerts created."
        )

    print(
        "New-order alerts processed: "
        f"{processed_count}"
    )

    print()


def show_financial_analysis_started() -> None:
    """
    Display the start of automated financial analysis.
    """

    print("Financial analysis")
    print("------------------")


def show_financial_processing_count(
    processed_count: int,
) -> None:
    """
    Display the number of stored orders processed financially.
    """

    print(
        "Orders financially processed: "
        f"{processed_count}"
    )

    print()


def show_missing_cost_alert_summary(
    *,
    processed_alerts: list[dict],
    resolved_items: list[dict],
) -> None:
    """
    Display the missing-cost alert lifecycle summary.
    """

    print("Missing-cost alert processing")
    print("-----------------------------")

    if processed_alerts:
        for alert in processed_alerts:
            print(
                "Active missing-cost alert: "
                f"{alert['title']} "
                f"(Alert ID: {alert['id']}, "
                "Occurrences: "
                f"{alert['occurrence_count']})"
            )
    else:
        print(
            "No missing-cost alerts active."
        )

    for resolved_item in resolved_items:
        print(
            "Resolved missing-cost alert for "
            "SKU: "
            f"{resolved_item.get('sku') or 'NO-SKU'}"
        )

    print(
        "Missing-cost alerts processed: "
        f"{len(processed_alerts)}"
    )

    print(
        "Missing-cost alerts resolved: "
        f"{len(resolved_items)}"
    )

    print()


def show_financial_results(
    financial_results: list[dict],
) -> None:
    """
    Display per-order financial analysis results.

    This function formats already-computed financial data only.
    It does not calculate profit or access the database.
    """

    if not financial_results:
        print(
            "No stored orders available "
            "for financial analysis."
        )
        print()

    for result in financial_results:
        print("=" * 50)

        print(
            "Order: "
            f"{result['order_name']}"
        )

        print(
            "Financial status: "
            f"{result['financial_status'].upper()}"
        )

        print(
            "Line items seen: "
            f"{result['line_items_seen']}"
        )

        print(
            "Snapshots created: "
            f"{result['snapshots_created']}"
        )

        print(
            "Existing snapshots: "
            f"{result['existing_snapshots']}"
        )

        print(
            "Missing costs: "
            f"{result['missing_cost_count']}"
        )

        summary = result["summary"]

        if summary is not None:
            currency_code = (
                summary["currency_code"]
            )

            print()
            print("Financial summary")
            print("-----------------")

            print(
                "Merchandise revenue: "
                f"{summary['merchandise_revenue']} "
                f"{currency_code}"
            )

            print(
                "Product cost: "
                f"{summary['product_cost']} "
                f"{currency_code}"
            )

            print(
                "Estimated gross profit: "
                f"{summary['estimated_gross_profit']} "
                f"{currency_code}"
            )

            margin = (
                summary[
                    "gross_margin_percent"
                ]
            )

            if margin is not None:
                print(
                    "Gross margin: "
                    f"{margin}%"
                )
            else:
                print(
                    "Gross margin: N/A"
                )

            print(
                "Total quantity: "
                f"{summary['total_quantity']}"
            )

            print(
                "Financial line items: "
                f"{summary['line_items_count']}"
            )

        elif result["missing_cost_count"] > 0:
            print()
            print(
                "Missing cost configuration"
            )
            print(
                "--------------------------"
            )

            for missing_item in (
                result["missing_cost_items"]
            ):
                print(
                    "SKU: "
                    f"{missing_item.get('sku') or 'NO-SKU'}"
                )

                print(
                    "Variant ID: "
                    f"{missing_item.get('shopify_variant_id') or 'N/A'}"
                )

                print()

            print(
                "Profit summary unavailable "
                "until all product costs "
                "are configured."
            )

        else:
            print()
            print(
                "No financial summary "
                "is currently available."
            )

        print()


def show_financial_snapshot_status(
    stored_snapshot_count: int,
) -> None:
    """
    Display historical profit snapshot count.
    """

    print(
        "Financial snapshot verification"
    )
    print(
        "-------------------------------"
    )

    print(
        "Profit snapshots stored: "
        f"{stored_snapshot_count}"
    )

    print()


def show_alert_database_status(
    *,
    open_alert_count: int,
    total_alert_count: int,
) -> None:
    """
    Display alert database counts.
    """

    print("Alert database verification")
    print("---------------------------")

    print(
        f"Open alerts: {open_alert_count}"
    )

    print(
        "Total alert history: "
        f"{total_alert_count}"
    )

    print()

def show_application_banner() -> None:
    """
    Display the application banner.
    """

    print("Shopify Automation Lab")
    print("----------------------")


def show_sync_run_started(
    sync_run_id: int,
) -> None:
    """
    Display the newly created synchronization audit ID.
    """

    print(
        f"Sync run started: #{sync_run_id}"
    )
    print()


def show_shopify_authentication_started() -> None:
    """
    Display the start of Shopify authentication.
    """

    print("Authenticating with Shopify...")


def show_shopify_authentication_success() -> None:
    """
    Display successful Shopify authentication.
    """

    print("Authentication successful!")
    print()


def show_product_persistence_started() -> None:
    """
    Display the start of product persistence.
    """

    print("Saving products to SQLite...")


def show_product_persistence_success() -> None:
    """
    Display successful product persistence.
    """

    print("Products saved successfully!")
    print()


def show_order_persistence_started() -> None:
    """
    Display the start of order persistence.
    """

    print("Saving orders to SQLite...")


def show_order_persistence_success() -> None:
    """
    Display successful order persistence.
    """

    print("Orders saved successfully!")
    print()


def show_product_database_verification(
    *,
    shopify_products: int,
    database_products: int,
    shopify_variants: int,
    database_variants: int,
) -> None:
    """
    Display product/variant count verification data.
    """

    print("Product database verification")
    print("-----------------------------")

    print(
        f"Shopify products: {shopify_products}"
    )

    print(
        f"Database products: {database_products}"
    )

    print(
        f"Shopify variants: {shopify_variants}"
    )

    print(
        f"Database variants: {database_variants}"
    )

    print()


def show_product_database_verification_success() -> None:
    """
    Display successful Shopify-to-SQLite product verification.
    """

    print("=" * 50)

    print(
        "Shopify -> SQLite product "
        "persistence test: SUCCESS"
    )

    print()


def show_order_database_verification(
    *,
    shopify_orders: int,
    database_orders: int,
    shopify_line_items: int,
    database_line_items: int,
) -> None:
    """
    Display order/line-item count verification data.
    """

    print("Order database verification")
    print("---------------------------")

    print(
        f"Shopify orders: {shopify_orders}"
    )

    print(
        f"Database orders: {database_orders}"
    )

    print(
        "Shopify line items: "
        f"{shopify_line_items}"
    )

    print(
        "Database line items: "
        f"{database_line_items}"
    )

    print()


def show_order_database_verification_success() -> None:
    """
    Display successful Shopify-to-SQLite order verification.
    """

    print("=" * 50)

    print(
        "Shopify -> SQLite order "
        "persistence test: SUCCESS"
    )


def show_sync_audit(
    completed_sync_run: dict,
) -> None:
    """
    Display one completed synchronization audit record.
    """

    print()
    print("Synchronization audit")
    print("---------------------")

    print(
        f"Run ID: {completed_sync_run['id']}"
    )

    print(
        f"Started: "
        f"{completed_sync_run['started_at']}"
    )

    print(
        f"Completed: "
        f"{completed_sync_run['completed_at']}"
    )

    print(
        f"Status: "
        f"{completed_sync_run['status']}"
    )

    print(
        "Products seen: "
        f"{completed_sync_run['products_seen']}"
    )

    print(
        "Variants seen: "
        f"{completed_sync_run['variants_seen']}"
    )


def show_recent_sync_runs(
    recent_runs: list[dict],
) -> None:
    """
    Display recent synchronization history.
    """

    print()
    print("Recent synchronization runs")
    print("---------------------------")

    for run in recent_runs:
        print(
            f"Run #{run['id']} | "
            f"{run['status']} | "
            f"Products: {run['products_seen']} | "
            f"Variants: {run['variants_seen']}"
        )


def show_daily_report_success(
    daily_report_result: dict,
) -> None:
    """
    Display the formatted daily report and stored snapshot ID.
    """

    print()

    print(
        daily_report_result[
            "formatted_report"
        ]
    )

    print()

    print(
        "Daily report snapshot stored: "
        f"#{daily_report_result['report_id']}"
    )

    print()


def show_daily_report_failure() -> None:
    """
    Display isolated daily-report failure information.
    """

    print()
    print("Daily report generation failed.")

    print(
        "Synchronization remains successful; "
        "review the application log for details."
    )

    print()


def show_sync_failure(
    *,
    sync_run_id: int | None,
    error_message: str,
    sync_run_marked_failed: bool,
    failure_alert: dict | None,
) -> None:
    """
    Display synchronization failure state without performing
    audit or alert persistence.

    Failure recovery remains in main.py; this function only renders
    the already-computed outcome.
    """

    print()
    print("Synchronization audit")
    print("---------------------")

    print(
        "Run ID: "
        f"{sync_run_id if sync_run_id is not None else 'N/A'}"
    )

    print("Status: failed")

    print(
        f"Error: {error_message}"
    )

    if sync_run_id is not None:
        print(
            "Audit marked failed: "
            f"{'yes' if sync_run_marked_failed else 'no'}"
        )

    if failure_alert is not None:
        print()
        print("Synchronization failure alert")
        print("-----------------------------")

        print(
            f"Alert ID: {failure_alert['id']}"
        )

        print(
            f"Type: {failure_alert['alert_type']}"
        )

        print(
            f"Severity: {failure_alert['severity']}"
        )

        print(
            f"Status: {failure_alert['status']}"
        )

