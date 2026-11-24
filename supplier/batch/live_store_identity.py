"""V2.8B/10: exact Shopify shop-identity READ ONLY adapter.

The authenticated ShopifyClient sends ONLY this GraphQL *query*.  The
adapter never forwards caller-supplied query strings and has no mutation API.
"""
from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from typing import Any

SHOP_IDENTITY_QUERY = "query ShopifyAutomationLabStoreIdentity { shop { id myshopifyDomain } }"
SHOP_GID_RE = re.compile(r"gid://shopify/Shop/[1-9][0-9]*\Z")
SHOP_DOMAIN_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,59}[a-z0-9])?\.myshopify\.com\Z")


class StoreIdentityRejected(ValueError):
    """Fail-closed store-identity read or validation."""


@dataclass(frozen=True, slots=True)
class VerifiedShopIdentity:
    shop_id: str
    domain: str


class ShopifyStoreIdentityReadOnly:
    """Query the shop of the *configured authenticated client*.

    `store_domain` is the Shopify client's configured endpoint host. We do not
    accept an arbitrary observed domain from a CLI argument or payload. For
    integration tests the injected client can be a strict fake.
    """

    def __init__(self, client: Any) -> None:
        host = getattr(client, "store_domain", None)
        if (
            not callable(getattr(client, "graphql", None))
            or type(host) is not str
            or SHOP_DOMAIN_RE.fullmatch(host) is None
        ):
            raise StoreIdentityRejected("Shopify client or configured host is invalid")
        self._client = client
        self._configured_host = host
        self.read_queries = 0

    def read(self) -> VerifiedShopIdentity:
        """Perform one authenticated, allowlisted query, then strictly validate."""
        self.read_queries += 1
        try:
            response = self._client.graphql(SHOP_IDENTITY_QUERY, {})
        except Exception as exc:
            # Never leak raw authentication, HTTP, or response details.
            raise StoreIdentityRejected("authenticated shop identity unavailable") from exc
        shop = response.get("shop") if type(response) is dict else None
        if type(shop) is not dict or set(shop) != {"id", "myshopifyDomain"}:
            raise StoreIdentityRejected("shop identity payload invalid")
        gid, domain = shop["id"], shop["myshopifyDomain"]
        if (
            type(gid) is not str or SHOP_GID_RE.fullmatch(gid) is None
            or type(domain) is not str or SHOP_DOMAIN_RE.fullmatch(domain) is None
        ):
            raise StoreIdentityRejected("shop identity values invalid")
        if not hmac.compare_digest(self._configured_host, domain):
            raise StoreIdentityRejected("authenticated shop does not match client endpoint")
        return VerifiedShopIdentity(shop_id=gid, domain=domain)
