ORDERS_QUERY = """
query GetOrders($first: Int!, $after: String) {
    orders(
        first: $first,
        after: $after,
        sortKey: CREATED_AT,
        reverse: true
    ) {
        edges {
            cursor

            node {
                id
                name
                createdAt
                updatedAt

                displayFinancialStatus
                displayFulfillmentStatus

                totalPriceSet {
                    shopMoney {
                        amount
                        currencyCode
                    }
                }

                lineItems(first: 100) {
                    edges {
                        node {
                            id
                            title
                            sku
                            quantity

                            variant {
                                id
                            }

                            originalUnitPriceSet {
                                shopMoney {
                                    amount
                                    currencyCode
                                }
                            }
                        }
                    }

                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                }
            }
        }

        pageInfo {
            hasNextPage
            endCursor
        }
    }
}
"""