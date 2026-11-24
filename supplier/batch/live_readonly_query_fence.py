"""V2.8B/6: an allowlisted Shopify inventory *query* boundary.

Only the project's exact inventory-readback operation and two validated GIDs are
forwarded. A future mutation sender MUST NOT reuse this wrapper for writes.
This is defense in depth, not a replacement for least-privilege API scopes.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from supplier.batch.live_request_contract import INVENTORY_GID_RE, LOCATION_GID_RE
from supplier.execution.readback import INVENTORY_READBACK_QUERY


class ReadOnlyQueryRejected(ValueError):
    """A GraphQL operation is not allowlisted for read-only inspection."""


class ReadOnlyShopifyQueryFence:
    """Expose ONLY `graphql` with the exact inventory readback query.

    ShopifyClient.graphql internally uses HTTP POST even for queries; this is
    about the GraphQL *operation*, not the HTTP verb. No `authenticate`,
    `session`, or mutation method is proxied through this adapter.
    """

    def __init__(self, client: Any) -> None:
        if client is None or not callable(getattr(client, "graphql", None)):
            raise ReadOnlyQueryRejected("a GraphQL client is required")
        self._client = client
        self.read_queries = 0

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        if type(query) is not str or query != INVENTORY_READBACK_QUERY:
            raise ReadOnlyQueryRejected("GraphQL operation is not on the read-only allowlist")
        if not isinstance(variables, dict) or set(variables) != {
            "inventoryItemId", "locationId"
        }:
            raise ReadOnlyQueryRejected("read-only query variables are invalid")
        item_id = variables["inventoryItemId"]
        location_id = variables["locationId"]
        if (
            type(item_id) is not str
            or INVENTORY_GID_RE.fullmatch(item_id) is None
            or type(location_id) is not str
            or LOCATION_GID_RE.fullmatch(location_id) is None
        ):
            raise ReadOnlyQueryRejected("inventory item or location GID is invalid")
        # Count a request before forwarding; even a network timeout may have
        # performed a real read. No mutation can be forwarded by this wrapper.
        self.read_queries += 1
        data = self._client.graphql(INVENTORY_READBACK_QUERY, deepcopy(variables))
        # The existing readback adapter historically coerces these flags with
        # bool(...). Reject string/numeric stand-ins before that conversion,
        # otherwise e.g. bool("false") would incorrectly look like True.
        item = data.get("inventoryItem") if isinstance(data, dict) else None
        if isinstance(item, dict):
            if type(item.get("tracked")) is not bool:
                raise ReadOnlyQueryRejected("Shopify tracked flag must be Boolean")
            level = item.get("inventoryLevel")
            if isinstance(level, dict):
                location = level.get("location")
                if (type(level.get("isActive")) is not bool
                        or not isinstance(location, dict)
                        or type(location.get("isActive")) is not bool):
                    raise ReadOnlyQueryRejected("Shopify inventory activity flags must be Boolean")
        return data
