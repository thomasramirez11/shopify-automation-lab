import requests


class ShopifyClient:
    """Handles authentication and communication with Shopify's Admin API."""

    def __init__(
        self,
        store_domain: str,
        client_id: str,
        client_secret: str,
        api_version: str,
    ):
        self.store_domain = store_domain
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_version = api_version

        self.access_token = None
        self.token_expires_in = None

        # Reuse one HTTP session for our Shopify requests.
        self.session = requests.Session()

    def authenticate(self) -> None:
        """Exchange Shopify app credentials for a temporary access token."""

        url = f"https://{self.store_domain}/admin/oauth/access_token"

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        try:
            response = self.session.post(
                url,
                data=payload,
                headers={"Accept": "application/json"},
                timeout=15,
            )

            response.raise_for_status()

        except requests.RequestException as error:
            raise ConnectionError(
                "Could not authenticate with Shopify."
            ) from error

        data = response.json()

        access_token = data.get("access_token")

        if not access_token:
            raise RuntimeError(
                "Shopify responded successfully but no access token was returned."
            )

        self.access_token = access_token
        self.token_expires_in = data.get("expires_in")

    def graphql(
        self,
        query: str,
        variables: dict | None = None,
    ) -> dict:
        """Send a GraphQL query to Shopify."""

        if not self.access_token:
            self.authenticate()

        url = (
            f"https://{self.store_domain}"
            f"/admin/api/{self.api_version}/graphql.json"
        )

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.access_token,
        }

        payload = {
            "query": query,
            "variables": variables or {},
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=headers,
                timeout=15,
            )

            response.raise_for_status()

        except requests.RequestException as error:
            raise ConnectionError(
                "Could not communicate with Shopify's GraphQL API."
            ) from error

        data = response.json()

        if data.get("errors"):
            raise RuntimeError(
                f"Shopify GraphQL error: {data['errors']}"
            )

        return data["data"]