from config.settings import (
    SHOPIFY_API_VERSION,
    SHOPIFY_CLIENT_ID,
    SHOPIFY_CLIENT_SECRET,
    SHOPIFY_STORE_DOMAIN,
)

from repositories.product_repository import ProductRepository
from repositories.sync_run_repository import SyncRunRepository
from services.product_service import ProductService
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
        product_repository = ProductRepository()

        # --------------------------------------------------
        # 4. Retrieve products from Shopify
        # --------------------------------------------------

        print("Retrieving products...")

        products = product_service.get_all_products()

        print(f"Products found: {len(products)}")
        print()

        # --------------------------------------------------
        # 5. Display Shopify product data
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
                print(f"  SKU: {variant['sku'] or 'NO-SKU'}")
                print(f"  Price: ${variant['price']}")
                print(
                    "  Inventory: "
                    f"{variant['inventoryQuantity']}"
                )
                print()

        print("=" * 50)
        print("Product retrieval test: SUCCESS")
        print()

        # --------------------------------------------------
        # 6. Persist Shopify products into SQLite
        # --------------------------------------------------

        print("Saving products to SQLite...")

        for product in products:
            product_repository.save_product(product)

        print("Products saved successfully!")
        print()

        # --------------------------------------------------
        # 7. Read the data back from SQLite
        # --------------------------------------------------

        stored_products = product_repository.get_all_products()
        stored_variants = product_repository.get_all_variants()

        expected_variant_count = sum(
            len(product["variants"]["edges"])
            for product in products
        )

        print("Database verification")
        print("---------------------")
        print(f"Shopify products: {len(products)}")
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

        # --------------------------------------------------
        # 8. Verify persistence
        # --------------------------------------------------
        

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
                "Shopify -> SQLite "
                "persistence test: SUCCESS"
            )
        else:
            raise RuntimeError(
                "Shopify and SQLite record counts "
                "do not match."
            )

        # --------------------------------------------------
        # 9. Mark synchronization successful
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
        # 11. Display recent synchronization history
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
        # 12. Mark synchronization failed
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