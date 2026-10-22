import logging
import os

from config.logging_config import setup_logging
from config.settings import (
    LOW_INVENTORY_THRESHOLD,
    SHOPIFY_API_VERSION,
    SHOPIFY_CLIENT_ID,
    SHOPIFY_CLIENT_SECRET,
    SHOPIFY_STORE_DOMAIN,
)

from repositories.alert_repository import AlertRepository
from repositories.cost_repository import CostRepository
from repositories.order_repository import OrderRepository
from repositories.product_repository import ProductRepository
from repositories.profit_snapshot_repository import (
    ProfitSnapshotRepository,
)
from repositories.sync_run_repository import SyncRunRepository
from services.alert_service import AlertService
from services.financial_processing_service import (
    FinancialProcessingService,
)
from services.order_service import OrderService
from services.product_service import ProductService
from services.profit_service import ProfitService
from shopify.client import ShopifyClient


logger = logging.getLogger(__name__)


def main():
    log_file = setup_logging()

    logger.info("Shopify Automation Lab synchronization starting.")

    print("Shopify Automation Lab")
    print("----------------------")

    # --------------------------------------------------
    # Create failure-safe audit and alert dependencies
    # --------------------------------------------------

    sync_run_repository = SyncRunRepository()
    alert_repository = AlertRepository()
    alert_service = AlertService(
        alert_repository=alert_repository,
    )

    sync_run_id = None

    try:
        # --------------------------------------------------
        # Create synchronization audit record
        # --------------------------------------------------

        sync_run_id = sync_run_repository.start_run()

        print(f"Sync run started: #{sync_run_id}")
        print()

        logger.info(
            "Synchronization run #%s started. Log file: %s",
            sync_run_id,
            log_file,
        )

        # Controlled Stage 6.8 failure hook.
        # Disabled by default and enabled only through the
        # current process environment during testing.
        if (
            os.getenv(
                "SHOPIFY_AUTOMATION_TEST_SYNC_FAILURE"
            )
            == "1"
        ):
            raise RuntimeError(
                "Intentional Stage 6.8 "
                "synchronization failure test"
            )

        # --------------------------------------------------
        # 1. Create Shopify client
        # --------------------------------------------------

        client = ShopifyClient(
            store_domain=SHOPIFY_STORE_DOMAIN,
            client_id=SHOPIFY_CLIENT_ID,
            client_secret=SHOPIFY_CLIENT_SECRET,
            api_version=SHOPIFY_API_VERSION,
        )

        # --------------------------------------------------
        # 2. Authenticate with Shopify
        # --------------------------------------------------

        print("Authenticating with Shopify...")
        client.authenticate()

        print("Authentication successful!")
        print()

        logger.info("Shopify authentication successful.")

        # --------------------------------------------------
        # 3. Create application services
        # --------------------------------------------------

        product_service = ProductService(client)
        order_service = OrderService(client)
        profit_service = ProfitService()

        # --------------------------------------------------
        # 4. Create repositories
        # --------------------------------------------------

        product_repository = ProductRepository()
        order_repository = OrderRepository()
        cost_repository = CostRepository()

        profit_snapshot_repository = (
            ProfitSnapshotRepository()
        )

        # --------------------------------------------------
        # 5. Create alert and financial processing services
        # --------------------------------------------------

        financial_processing_service = (
            FinancialProcessingService(
                order_repository=order_repository,
                cost_repository=cost_repository,
                snapshot_repository=(
                    profit_snapshot_repository
                ),
                profit_service=profit_service,
            )
        )

        # --------------------------------------------------
        # 6. Retrieve products from Shopify
        # --------------------------------------------------

        print("Retrieving products...")

        products = product_service.get_all_products()

        print(f"Products found: {len(products)}")
        print()

        logger.info(
            "Retrieved %s products from Shopify.",
            len(products),
        )

        # --------------------------------------------------
        # 7. Display Shopify product data
        # --------------------------------------------------

        for product in products:
            print("=" * 50)

            print(f"PRODUCT: {product['title']}")
            print(f"ID: {product['id']}")
            print(f"Vendor: {product['vendor'] or 'N/A'}")
            print(f"Status: {product['status']}")

            variant_edges = product["variants"]["edges"]

            print(f"Variants: {len(variant_edges)}")
            print()

            for variant_edge in variant_edges:
                variant = variant_edge["node"]

                print(f"  Variant: {variant['title']}")
                print(
                    f"  SKU: "
                    f"{variant['sku'] or 'NO-SKU'}"
                )
                print(
                    f"  Price: "
                    f"${variant['price']}"
                )
                print(
                    "  Inventory: "
                    f"{variant['inventoryQuantity']}"
                )
                print()

        print("=" * 50)
        print("Product retrieval test: SUCCESS")
        print()

        # --------------------------------------------------
        # 8. Retrieve orders from Shopify
        # --------------------------------------------------

        print("Retrieving orders...")

        orders = order_service.get_all_orders()

        print(f"Orders found: {len(orders)}")
        print()

        logger.info(
            "Retrieved %s orders from Shopify.",
            len(orders),
        )

        # --------------------------------------------------
        # 9. Display Shopify order data
        # --------------------------------------------------

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

            print(f"ORDER: {order['name']}")
            print(f"ID: {order['id']}")
            print(
                f"Created: "
                f"{order['createdAt']}"
            )
            print(
                f"Updated: "
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
                f"Line items: "
                f"{len(line_item_edges)}"
            )
            print()

            for line_item_edge in line_item_edges:
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
                    f"  Item: "
                    f"{line_item['title']}"
                )

                print(
                    f"  SKU: "
                    f"{line_item.get('sku') or 'NO-SKU'}"
                )

                print(
                    f"  Quantity: "
                    f"{line_item['quantity']}"
                )

                print(
                    f"  Unit price: "
                    f"${unit_amount} "
                    f"{unit_currency}"
                )

                print(
                    f"  Variant ID: "
                    f"{variant.get('id') or 'N/A'}"
                )

                print()

        print("=" * 50)
        print("Order retrieval test: SUCCESS")
        print()

        # --------------------------------------------------
        # 10. Persist Shopify products into SQLite
        # --------------------------------------------------

        print("Saving products to SQLite...")

        for product in products:
            product_repository.save_product(
                product
            )

        print("Products saved successfully!")
        print()

        logger.info(
            "Product persistence completed. products=%s",
            len(products),
        )

        # --------------------------------------------------
        # 10B. Keep low-inventory alerts synchronized
        # --------------------------------------------------

        print("Low-inventory alert processing")
        print("------------------------------")
        print(
            f"Configured threshold: "
            f"{LOW_INVENTORY_THRESHOLD}"
        )

        low_inventory_alerts_processed = []
        low_inventory_alerts_resolved = []
        inventory_variants_checked = 0
        untracked_variants_skipped = 0

        for product in products:
            product_title = (
                product.get("title")
                or "Unnamed product"
            )

            variant_edges = (
                product
                .get("variants", {})
                .get("edges", [])
            )

            for variant_edge in variant_edges:
                variant = (
                    variant_edge.get("node")
                    or {}
                )

                inventory_item = (
                    variant.get("inventoryItem")
                    or {}
                )

                if (
                    inventory_item.get("tracked")
                    is False
                ):
                    untracked_variants_skipped += 1
                    continue

                inventory_quantity = (
                    variant.get(
                        "inventoryQuantity"
                    )
                )

                if inventory_quantity is None:
                    logger.info(
                        "Skipping inventory alert check "
                        "for variant '%s' because no "
                        "inventory quantity is available.",
                        variant.get("id"),
                    )
                    continue

                inventory_variants_checked += 1

                if (
                    inventory_quantity
                    <= LOW_INVENTORY_THRESHOLD
                ):
                    alert = (
                        alert_service
                        .create_low_inventory_alert(
                            product_title=product_title,
                            variant=variant,
                            threshold=(
                                LOW_INVENTORY_THRESHOLD
                            ),
                        )
                    )

                    low_inventory_alerts_processed.append(
                        alert
                    )

                    print(
                        "Active low-inventory alert: "
                        f"{alert['title']} "
                        f"(Alert ID: {alert['id']}, "
                        f"Occurrences: "
                        f"{alert['occurrence_count']})"
                    )

                else:
                    sku = variant.get("sku")
                    variant_id = variant.get("id")

                    if variant_id or sku:
                        resolved = (
                            alert_service
                            .resolve_low_inventory_alert(
                                sku=sku,
                                variant_id=variant_id,
                            )
                        )

                        if resolved:
                            low_inventory_alerts_resolved.append(
                                {
                                    "product_title": (
                                        product_title
                                    ),
                                    "sku": sku,
                                    "shopify_variant_id": (
                                        variant_id
                                    ),
                                    "inventory_quantity": (
                                        inventory_quantity
                                    ),
                                }
                            )

                            print(
                                "Resolved low-inventory "
                                "alert for SKU: "
                                f"{sku or 'NO-SKU'} "
                                f"(Inventory: "
                                f"{inventory_quantity})"
                            )

        if not low_inventory_alerts_processed:
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
            f"{len(low_inventory_alerts_processed)}"
        )

        print(
            "Low-inventory alerts resolved: "
            f"{len(low_inventory_alerts_resolved)}"
        )
        print()

        logger.info(
            (
                "Low-inventory alert processing "
                "completed. threshold=%s checked=%s "
                "untracked_skipped=%s processed=%s "
                "resolved=%s"
            ),
            LOW_INVENTORY_THRESHOLD,
            inventory_variants_checked,
            untracked_variants_skipped,
            len(low_inventory_alerts_processed),
            len(low_inventory_alerts_resolved),
        )

        # --------------------------------------------------
        # 11. Persist Shopify orders and detect new orders
        # --------------------------------------------------

        print("Saving orders to SQLite...")

        new_orders = []

        for order in orders:
            is_new_order = (
                order_repository.save_order(
                    order
                )
            )

            if is_new_order:
                new_orders.append(order)

        print("Orders saved successfully!")
        print()

        logger.info(
            "Order persistence completed. orders=%s new_orders=%s",
            len(orders),
            len(new_orders),
        )

        # --------------------------------------------------
        # 12. Display newly detected orders
        # --------------------------------------------------

        print("New order detection")
        print("-------------------")

        print(
            f"New orders detected: "
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
            print(f"Order: {order['name']}")

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
                f"Line items: "
                f"{len(line_item_edges)}"
            )

        print()

        # --------------------------------------------------
        # 13. Create persistent alerts for new orders
        # --------------------------------------------------

        print("New-order alert processing")
        print("--------------------------")

        new_order_alerts = []

        for order in new_orders:
            alert = alert_service.create_new_order_alert(
                order
            )

            new_order_alerts.append(alert)

            print(
                f"Alert created for order "
                f"{order['name']} "
                f"(Alert ID: {alert['id']})"
            )

        if not new_order_alerts:
            print("No new-order alerts created.")

        print(
            f"New-order alerts processed: "
            f"{len(new_order_alerts)}"
        )
        print()

        logger.info(
            (
                "New-order alert processing completed. "
                "new_orders=%s alerts_processed=%s"
            ),
            len(new_orders),
            len(new_order_alerts),
        )

        # --------------------------------------------------
        # 14. Automatically process order finances
        # --------------------------------------------------

        print("Financial analysis")
        print("------------------")

        stored_orders_for_financials = (
            order_repository.get_all_orders()
        )

        financial_results = []
        missing_cost_alerts_processed = []
        missing_cost_alerts_resolved = []

        for stored_order in (
            stored_orders_for_financials
        ):
            result = (
                financial_processing_service
                .process_order(
                    stored_order
                )
            )

            financial_results.append(
                result
            )

            # ----------------------------------------------
            # Keep missing-cost alerts synchronized with
            # the current financial-processing state.
            # ----------------------------------------------

            for item_result in result["item_results"]:
                item_status = item_result["status"]

                if item_status == "missing_cost":
                    alert = (
                        alert_service
                        .create_missing_cost_alert(
                            order_name=result["order_name"],
                            missing_item=item_result,
                        )
                    )

                    missing_cost_alerts_processed.append(
                        alert
                    )

                elif item_status in {
                    "created",
                    "existing_snapshot",
                }:
                    sku = item_result.get("sku")
                    variant_id = item_result.get(
                        "shopify_variant_id"
                    )

                    # Some custom Shopify line items may
                    # have neither a variant ID nor a SKU.
                    # In that case there is no stable key
                    # for a missing-cost alert to resolve.
                    if variant_id or sku:
                        resolved = (
                            alert_service
                            .resolve_missing_cost_alert(
                                sku=sku,
                                variant_id=variant_id,
                            )
                        )

                        if resolved:
                            missing_cost_alerts_resolved.append(
                                {
                                    "order_name": result[
                                        "order_name"
                                    ],
                                    "sku": sku,
                                    "shopify_variant_id": (
                                        variant_id
                                    ),
                                }
                            )

            if result["missing_cost_count"] > 0:
                logger.warning(
                    (
                        "Financial analysis incomplete for order %s. "
                        "missing_costs=%s"
                    ),
                    result["order_name"],
                    result["missing_cost_count"],
                )
            else:
                logger.info(
                    (
                        "Financial analysis complete for order %s. "
                        "snapshots_created=%s existing_snapshots=%s"
                    ),
                    result["order_name"],
                    result["snapshots_created"],
                    result["existing_snapshots"],
                )

        print(
            f"Orders financially processed: "
            f"{len(financial_results)}"
        )

        print()

        # --------------------------------------------------
        # Missing-cost alert lifecycle summary
        # --------------------------------------------------

        print("Missing-cost alert processing")
        print("-----------------------------")

        if missing_cost_alerts_processed:
            for alert in missing_cost_alerts_processed:
                print(
                    f"Active missing-cost alert: "
                    f"{alert['title']} "
                    f"(Alert ID: {alert['id']}, "
                    f"Occurrences: "
                    f"{alert['occurrence_count']})"
                )
        else:
            print("No missing-cost alerts active.")

        if missing_cost_alerts_resolved:
            for resolved_item in (
                missing_cost_alerts_resolved
            ):
                print(
                    "Resolved missing-cost alert for "
                    f"SKU: "
                    f"{resolved_item.get('sku') or 'NO-SKU'}"
                )

        print(
            "Missing-cost alerts processed: "
            f"{len(missing_cost_alerts_processed)}"
        )

        print(
            "Missing-cost alerts resolved: "
            f"{len(missing_cost_alerts_resolved)}"
        )
        print()

        logger.info(
            (
                "Missing-cost alert processing completed. "
                "processed=%s resolved=%s"
            ),
            len(missing_cost_alerts_processed),
            len(missing_cost_alerts_resolved),
        )

        # --------------------------------------------------
        # 15. Display financial analysis
        # --------------------------------------------------

        if not financial_results:
            print(
                "No stored orders available "
                "for financial analysis."
            )
            print()

        for result in financial_results:
            print("=" * 50)

            print(
                f"Order: "
                f"{result['order_name']}"
            )

            print(
                "Financial status: "
                f"{result['financial_status'].upper()}"
            )

            print(
                f"Line items seen: "
                f"{result['line_items_seen']}"
            )

            print(
                f"Snapshots created: "
                f"{result['snapshots_created']}"
            )

            print(
                f"Existing snapshots: "
                f"{result['existing_snapshots']}"
            )

            print(
                f"Missing costs: "
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
                        f"Gross margin: "
                        f"{margin}%"
                    )
                else:
                    print(
                        "Gross margin: N/A"
                    )

                print(
                    f"Total quantity: "
                    f"{summary['total_quantity']}"
                )

                print(
                    f"Financial line items: "
                    f"{summary['line_items_count']}"
                )

            elif result["missing_cost_count"] > 0:
                print()
                print("Missing cost configuration")
                print("--------------------------")

                for missing_item in (
                    result["missing_cost_items"]
                ):
                    print(
                        f"SKU: "
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

        # --------------------------------------------------
        # 16. Financial snapshot status
        # --------------------------------------------------

        stored_snapshot_count = (
            profit_snapshot_repository
            .count_snapshots()
        )

        logger.info(
            "Financial snapshot count: %s",
            stored_snapshot_count,
        )

        print("Financial snapshot verification")
        print("-------------------------------")

        print(
            f"Profit snapshots stored: "
            f"{stored_snapshot_count}"
        )

        print()

        # --------------------------------------------------
        # Alert database status
        # --------------------------------------------------

        open_alert_count = (
            alert_repository.count_open_alerts()
        )

        total_alert_count = (
            alert_repository.count_all_alerts()
        )

        print("Alert database verification")
        print("---------------------------")
        print(f"Open alerts: {open_alert_count}")
        print(f"Total alert history: {total_alert_count}")
        print()

        logger.info(
            "Alert counts. open=%s total_history=%s",
            open_alert_count,
            total_alert_count,
        )

        # --------------------------------------------------
        # 17. Read product data back from SQLite
        # --------------------------------------------------

        stored_products = (
            product_repository.get_all_products()
        )

        stored_variants = (
            product_repository.get_all_variants()
        )

        expected_variant_count = sum(
            len(product["variants"]["edges"])
            for product in products
        )

        # --------------------------------------------------
        # 18. Read order data back from SQLite
        # --------------------------------------------------

        stored_order_count = (
            order_repository.count_orders()
        )

        stored_line_item_count = (
            order_repository.count_line_items()
        )

        expected_line_item_count = sum(
            len(order["lineItems"]["edges"])
            for order in orders
        )

        # --------------------------------------------------
        # 19. Verify product database state
        # --------------------------------------------------

        print("Product database verification")
        print("-----------------------------")

        print(
            f"Shopify products: "
            f"{len(products)}"
        )

        print(
            f"Database products: "
            f"{len(stored_products)}"
        )

        print(
            f"Shopify variants: "
            f"{expected_variant_count}"
        )

        print(
            f"Database variants: "
            f"{len(stored_variants)}"
        )

        print()

        products_match = (
            len(products)
            == len(stored_products)
        )

        variants_match = (
            expected_variant_count
            == len(stored_variants)
        )

        if products_match and variants_match:
            print("=" * 50)

            print(
                "Shopify -> SQLite product "
                "persistence test: SUCCESS"
            )
        else:
            raise RuntimeError(
                "Shopify and SQLite product "
                "record counts do not match."
            )

        print()

        # --------------------------------------------------
        # 20. Verify order database state
        # --------------------------------------------------

        print("Order database verification")
        print("---------------------------")

        print(
            f"Shopify orders: "
            f"{len(orders)}"
        )

        print(
            f"Database orders: "
            f"{stored_order_count}"
        )

        print(
            f"Shopify line items: "
            f"{expected_line_item_count}"
        )

        print(
            f"Database line items: "
            f"{stored_line_item_count}"
        )

        print()

        orders_match = (
            len(orders)
            == stored_order_count
        )

        line_items_match = (
            expected_line_item_count
            == stored_line_item_count
        )

        if orders_match and line_items_match:
            print("=" * 50)

            print(
                "Shopify -> SQLite order "
                "persistence test: SUCCESS"
            )
        else:
            raise RuntimeError(
                "Shopify and SQLite order "
                "record counts do not match."
            )

        # --------------------------------------------------
        # 21. Mark synchronization successful
        # --------------------------------------------------

        sync_run_repository.mark_success(
            run_id=sync_run_id,
            products_seen=len(products),
            variants_seen=expected_variant_count,
        )

        logger.info(
            (
                "Synchronization run #%s completed successfully. "
                "products=%s variants=%s orders=%s line_items=%s "
                "profit_snapshots=%s"
            ),
            sync_run_id,
            len(products),
            expected_variant_count,
            len(orders),
            expected_line_item_count,
            stored_snapshot_count,
        )

        completed_sync_run = (
            sync_run_repository.get_run_by_id(
                sync_run_id
            )
        )

        print()
        print("Synchronization audit")
        print("---------------------")

        print(
            f"Run ID: "
            f"{completed_sync_run['id']}"
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

        # --------------------------------------------------
        # 22. Display recent synchronization history
        # --------------------------------------------------

        recent_runs = (
            sync_run_repository.get_recent_runs(
                limit=5
            )
        )

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

    except Exception as exc:
        # --------------------------------------------------
        # 23. Failure isolation + synchronization alerting
        # --------------------------------------------------

        error_type = type(exc).__name__
        error_message = (
            f"{error_type}: {exc}"
        )

        # Record the original traceback before attempting any
        # secondary database operations. This ensures that a
        # failure while writing the audit or alert cannot hide
        # the primary synchronization failure.
        logger.exception(
            "Synchronization run %s failed.",
            (
                f"#{sync_run_id}"
                if sync_run_id is not None
                else "before an audit ID was created"
            ),
        )

        sync_run_marked_failed = False
        failure_alert = None

        if sync_run_id is not None:
            try:
                sync_run_repository.mark_failed(
                    run_id=sync_run_id,
                    error_message=error_message,
                )
                sync_run_marked_failed = True

            except Exception:
                logger.exception(
                    "Secondary failure: could not mark "
                    "synchronization run #%s as failed.",
                    sync_run_id,
                )

            try:
                failure_alert = (
                    alert_service
                    .create_sync_failure_alert(
                        sync_run_id=sync_run_id,
                        error_type=error_type,
                    )
                )

            except Exception:
                logger.exception(
                    "Secondary failure: could not persist "
                    "SYNC_FAILURE alert for run #%s.",
                    sync_run_id,
                )
        else:
            logger.critical(
                "Synchronization failed before a sync-run "
                "audit record could be created."
            )

        print()
        print("Synchronization audit")
        print("---------------------")

        print(
            "Run ID: "
            f"{sync_run_id if sync_run_id is not None else 'N/A'}"
        )
        print("Status: failed")
        print(f"Error: {error_message}")

        if sync_run_id is not None:
            print(
                "Audit marked failed: "
                f"{'yes' if sync_run_marked_failed else 'no'}"
            )

        if failure_alert is not None:
            print()
            print("Synchronization failure alert")
            print("-----------------------------")
            print(f"Alert ID: {failure_alert['id']}")
            print(f"Type: {failure_alert['alert_type']}")
            print(f"Severity: {failure_alert['severity']}")
            print(f"Status: {failure_alert['status']}")

        # Re-raise the ORIGINAL exception. Secondary failure
        # handling above is intentionally isolated.
        raise


if __name__ == "__main__":
    main()