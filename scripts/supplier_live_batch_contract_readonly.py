"""V2.8B/3: real Shopify READ-ONLY preflight -> immutable GraphQL preview.

No SQLite writes, no intent reservation, no dispatch journal and no mutation call.
The candidate is a SYNTHETIC proposal based on V1 SQLite, NOT supplier feed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from supplier.batch.approval import evaluate_batch_approval  # noqa: E402
from supplier.batch.live_preflight_bridge import prepare_from_fresh_preflight  # noqa: E402
from supplier.batch.live_request_contract import LOCATION_GID_RE  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Shopify V2.8B/3 contract proof")
    parser.add_argument("--location-id", required=True, help="Exact verified Shopify Location GID")
    parser.add_argument("--approve-manifest", default=None, help="Exact current manifest SHA-256")
    args = parser.parse_args(argv)
    if LOCATION_GID_RE.fullmatch(args.location_id) is None:
        parser.error("location-id must be a valid Shopify Location GID")

    # Import only the proven V2.8A baseline/adapter helpers, not its CLI.
    from scripts.supplier_live_batch_preflight import (  # noqa: E402
        build_read_only_candidate, build_client,
    )
    from supplier.execution.readback import ShopifyInventoryReadbackAdapter  # noqa: E402
    from supplier.execution.shopify_adapter import SQLiteInventoryTargetResolver  # noqa: E402

    plan, manifest = build_read_only_candidate()
    approval = evaluate_batch_approval(
        plan=plan, manifest=manifest, approved_manifest_fingerprint=args.approve_manifest,
    )
    print("SHOPIFY AUTOMATION LAB — V2.8B/3 REAL READ-ONLY REQUEST PREVIEW")
    print("CANDIDATE: V1 SQLITE BASELINE + SYNTHETIC DELTAS (NOT SUPPLIER FEED)")
    print("MODE: READ ONLY — NO DISPATCH / NO SQLITE WRITES")
    print("MANIFEST FINGERPRINT:", manifest.manifest_fingerprint)
    print("APPROVAL:", approval.status.value.upper())
    if not approval.can_execute:
        print("SHOPIFY NETWORK CALLS: 0")
        print("LIVE SHOPIFY WRITES: 0")
        print("RE-RUN:")
        print("python scripts/supplier_live_batch_contract_readonly.py "
              f"--location-id {args.location_id} "
              f"--approve-manifest {manifest.manifest_fingerprint}")
        return 0

    # The V2.8B bridge calls evaluate_live_batch_preflight() which exclusively
    # uses read_available() on the Shopify readback adapter.
    client = build_client()
    prepared = prepare_from_fresh_preflight(
        plan=plan, manifest=manifest, approval_report=approval,
        target_resolver=SQLiteInventoryTargetResolver(location_id=args.location_id),
        readback_port=ShopifyInventoryReadbackAdapter(client),
        expected_location_id=args.location_id,
    )
    print("PREFLIGHT:", prepared.preflight.status.value.upper())
    print("OPERATION ID (EPHEMERAL; NOT RESERVED):", prepared.preview.operation_id)
    print("REQUEST DIGEST:", prepared.request_digest)
    print("CAS TARGETS (NOT SENT):")
    for sku, item in zip(prepared.preview.skus, prepared.preview.variables["input"]["quantities"]):
        print(f"  {sku}: {item['changeFromQuantity']} -> {item['quantity']}")
    print("SHOPIFY MUTATIONS: DISABLED")
    print("SQLITE WRITES: 0")
    print("STATUS: LIVE READ-ONLY BRIDGE READY — EXECUTION DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
