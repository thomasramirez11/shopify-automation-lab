from config.settings import (
    SHOPIFY_API_VERSION,
    SHOPIFY_CLIENT_ID,
    SHOPIFY_CLIENT_SECRET,
    SHOPIFY_STORE_DOMAIN,
)

from repositories.cost_repository import CostRepository
from repositories.order_repository import OrderRepository
from repositories.product_repository import ProductRepository
from repositories.profit_snapshot_repository import (
    ProfitSnapshotRepository,
)
from repositories.sync_run_repository import SyncRunRepository
from services.financial_processing_service import (
    FinancialProcessingService,
)
from services.order_service import OrderService
from services.product_service import ProductService
from services.profit_service import ProfitService
from shopify.client import ShopifyClient


def main():
    print("Shopify Automation Lab")
    print("----------------------")

    # --------------------------------------------------
    # Create synchronization audit record
    # --------------------------------------------------

    sync_run_repository = SyncRunRepository()
    sync_run_id = sync_run_repository.start_run()

    print(f"Sync run started: #{sync_run_id}")
    print()

    try:
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
        # 5. Create financial processing service
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
        # 13. Automatically process order finances
        # --------------------------------------------------

        print("Financial analysis")
        print("------------------")

        stored_orders_for_financials = (
            order_repository.get_all_orders()
        )

        financial_results = []

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

        print(
            f"Orders financially processed: "
            f"{len(financial_results)}"
        )

        print()

        # --------------------------------------------------
        # 14. Display financial analysis
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
        # 15. Financial snapshot status
        # --------------------------------------------------

        stored_snapshot_count = (
            profit_snapshot_repository
            .count_snapshots()
        )

        print("Financial snapshot verification")
        print("-------------------------------")

        print(
            f"Profit snapshots stored: "
            f"{stored_snapshot_count}"
        )

        print()

        # --------------------------------------------------
        # 16. Read product data back from SQLite
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
        # 17. Read order data back from SQLite
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
        # 18. Verify product database state
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
        # 19. Verify order database state
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
        # 20. Mark synchronization successful
        # --------------------------------------------------

        sync_run_repository.mark_success(
            run_id=sync_run_id,
            products_seen=len(products),
            variants_seen=expected_variant_count,
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
        # 21. Display recent synchronization history
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
        # 22. Mark synchronization failed
        # --------------------------------------------------

        error_message = (
            f"{type(exc).__name__}: {exc}"
        )

        sync_run_repository.mark_failed(
            run_id=sync_run_id,
            error_message=error_message,
        )

        print()
        print("Synchronization audit")
        print("---------------------")

        print(f"Run ID: {sync_run_id}")
        print("Status: failed")
        print(f"Error: {error_message}")

        # Re-raise the original exception so Python still
        # reports the synchronization as a real failure.
        raise


if __name__ == "__main__":
    main()