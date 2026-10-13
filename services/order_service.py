from shopify.queries.orders import ORDERS_QUERY


class OrderService:
    """Handles Shopify order retrieval logic."""

    def __init__(self, shopify_client):
        self.shopify_client = shopify_client

    def get_all_orders(
        self,
        page_size: int = 50,
    ) -> list:
        """
        Retrieve all accessible Shopify orders using cursor pagination.

        Orders are returned newest first.

        Each order currently retrieves up to 100 line items.
        If Shopify reports more than 100 line items for an order,
        the service raises an error instead of silently returning
        incomplete order data.
        """

        if not 1 <= page_size <= 250:
            raise ValueError(
                "page_size must be between 1 and 250."
            )

        orders = []
        after_cursor = None

        while True:
            variables = {
                "first": page_size,
                "after": after_cursor,
            }

            data = self.shopify_client.graphql(
                ORDERS_QUERY,
                variables,
            )

            order_connection = data["orders"]

            for edge in order_connection["edges"]:
                order = edge["node"]

                line_items = order["lineItems"]
                line_item_page_info = line_items["pageInfo"]

                if line_item_page_info["hasNextPage"]:
                    raise RuntimeError(
                        "Order "
                        f"{order['name']} "
                        "contains more than 100 line items. "
                        "Nested line-item pagination has not "
                        "been implemented yet."
                    )

                orders.append(order)

            page_info = order_connection["pageInfo"]

            if not page_info["hasNextPage"]:
                break

            after_cursor = page_info["endCursor"]

            if not after_cursor:
                raise RuntimeError(
                    "Shopify reported another order page "
                    "but returned no cursor."
                )

        return orders