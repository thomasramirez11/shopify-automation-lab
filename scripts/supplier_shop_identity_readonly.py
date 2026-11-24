"""V2.8B/10: authenticated Shopify shop identity, READ ONLY, NO WRITES.

This optional CLI performs exactly one allowlisted `shop` GraphQL query after
client authentication. It never loads/saves supplier batch operations.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supplier.batch.live_store_identity import (  # noqa: E402
    SHOP_GID_RE, ShopifyStoreIdentityReadOnly, StoreIdentityRejected,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Authenticated Shopify identity — read only")
    parser.add_argument("--expected-shop-id", default=None,
                        help="Previously verified exact Shopify Shop GID")
    args = parser.parse_args(argv)
    if args.expected_shop_id is not None and SHOP_GID_RE.fullmatch(args.expected_shop_id) is None:
        parser.error("--expected-shop-id must be a Shopify Shop GID")

    print("SHOPIFY AUTOMATION LAB — V2.8B/10 AUTHENTICATED SHOP IDENTITY")
    print("MODE: SHOP IDENTITY QUERY ONLY | LIVE MUTATIONS DISABLED")
    from scripts.supplier_live_batch_preflight import build_client
    try:
        reader = ShopifyStoreIdentityReadOnly(build_client())
        identity = reader.read()
    except Exception:
        print("IDENTITY STATUS: BLOCKED (unavailable or untrusted Shopify identity)")
        print("LIVE SHOPIFY WRITES: 0")
        return 2
    print("SHOP ID:", identity.shop_id)
    print("SHOP DOMAIN:", identity.domain)
    print("AUTHENTICATED SHOP QUERIES:", reader.read_queries)
    if args.expected_shop_id is None:
        print("IDENTITY STATUS: VERIFIED — PIN SHOP ID BEFORE FUTURE REVIEW")
    elif identity.shop_id == args.expected_shop_id:
        print("IDENTITY STATUS: PINNED SHOP ID MATCH")
    else:
        print("IDENTITY STATUS: SHOP ID MISMATCH — BLOCKED")
        print("LIVE SHOPIFY WRITES: 0")
        return 2
    print("LIVE SHOPIFY WRITES: 0")
    print("PROJECT SQLITE WRITES: 0")
    print("STATUS: AUTHENTICATED STORE READ VERIFIED — EXECUTION DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
