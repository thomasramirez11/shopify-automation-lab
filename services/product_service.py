from shopify.queries.products import PRODUCTS_QUERY


class ProductService:
    """Handles Shopify product retrieval logic."""

    def __init__(self, shopify_client):
        self.shopify_client = shopify_client

    def get_all_products(self, page_size: int = 50) -> list:
        """
        Retrieve all products from Shopify using cursor pagination.
        """

        products = []
        after_cursor = None

        while True:
            variables = {
                "first": page_size,
                "after": after_cursor,
            }

            data = self.shopify_client.graphql(
                PRODUCTS_QUERY,
                variables,
            )

            product_connection = data["products"]

            for edge in product_connection["edges"]:
                products.append(edge["node"])

            page_info = product_connection["pageInfo"]

            if not page_info["hasNextPage"]:
                break

            after_cursor = page_info["endCursor"]

            if not after_cursor:
                raise RuntimeError(
                    "Shopify reported another page but returned no cursor."
                )

        return products