PRODUCTS_QUERY = """
query GetProducts($first: Int!, $after: String) {
    products(first: $first, after: $after) {
        edges {
            cursor

            node {
                id
                title
                vendor
                status
                updatedAt

                variants(first: 100) {
                    edges {
                        node {
                            id
                            title
                            sku
                            price
                            inventoryQuantity

                            inventoryItem {
                                id
                                tracked
                            }
                        }
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