"""V2.8B/6 real Shopify READ-ONLY controller gate.

Builds the same small synthetic proposal as V2.8A. This script never stores
an intent, arms dispatch, records a recovery event, or sends a Shopify mutation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supplier.batch.approval import evaluate_batch_approval  # noqa: E402
from supplier.batch.live_preflight_bridge import prepare_from_fresh_preflight  # noqa: E402
from supplier.batch.live_readonly_inspection import inspect_fresh_candidate  # noqa: E402
from supplier.batch.live_readonly_query_fence import ReadOnlyShopifyQueryFence  # noqa: E402
from supplier.batch.live_request_contract import LOCATION_GID_RE  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shopify real read-only two-item controller check")
    parser.add_argument("--location-id", required=True, help="Exact Shopify Location GID")
    parser.add_argument("--approve-manifest", default=None, help="Current approved manifest SHA-256")
    args = parser.parse_args(argv)
    if LOCATION_GID_RE.fullmatch(args.location_id) is None:
        parser.error("location-id must be a Shopify Location GID")

    from scripts.supplier_live_batch_preflight import build_read_only_candidate, build_client
    from supplier.execution.shopify_adapter import SQLiteInventoryTargetResolver
    from supplier.execution.readback import ShopifyInventoryReadbackAdapter

    print("SHOPIFY AUTOMATION LAB — V2.8B/6 LIVE READ-ONLY CONTROLLER GATE")
    print("CANDIDATE: V1 SQLITE BASELINE + SYNTHETIC PROPOSAL (NOT SUPPLIER FEED)")
    print("MODE: READ ONLY | LIVE MUTATIONS: DISABLED | SQLITE WRITES: 0")
    plan, manifest = build_read_only_candidate()
    approval = evaluate_batch_approval(
        plan=plan, manifest=manifest,
        approved_manifest_fingerprint=args.approve_manifest,
    )
    print("MANIFEST FINGERPRINT:", manifest.manifest_fingerprint)
    print("APPROVAL STATUS:", approval.status.value.upper())
    if not approval.can_execute:
        print("LIVE SHOPIFY INVENTORY READS: 0")
        print("LIVE SHOPIFY WRITES: 0")
        print("RE-RUN:")
        print("python scripts/supplier_batch_readonly_gate.py "
              f"--location-id {args.location_id} "
              f"--approve-manifest {manifest.manifest_fingerprint}")
        return 0

    # The fence only forwards the exact known inventory *query* to ShopifyClient.
    client = ReadOnlyShopifyQueryFence(build_client())
    port = ShopifyInventoryReadbackAdapter(client)
    resolver = SQLiteInventoryTargetResolver(location_id=args.location_id)
    try:
        prepared = prepare_from_fresh_preflight(
            plan=plan, manifest=manifest, approval_report=approval,
            target_resolver=resolver, readback_port=port,
            expected_location_id=args.location_id,
        )
        report = inspect_fresh_candidate(prepared, readback_port=port)
    except Exception:
        # No raw network/API exception body should escape into logs.
        print("READ-ONLY GATE: BLOCKED (approval, preflight, or Shopify read unavailable)")
        print("LIVE SHOPIFY INVENTORY READS:", client.read_queries)
        print("LIVE SHOPIFY WRITES: 0")
        print("PROJECT SQLITE WRITES: 0")
        return 2

    print("PREFLIGHT STATUS:", prepared.preflight.status.value.upper())
    print("SECOND READ STATUS:", report.status.value)
    for item in report.items:
        print(f"  {item.sku}: baseline={item.baseline} fresh={item.observed} "
              f"proposed={item.proposed} classification={item.classification}")
    print("LIVE SHOPIFY INVENTORY READS:", client.read_queries)
    print("CAN CONTINUE TO OPERATOR REVIEW:", report.can_continue_to_operator_review)
    print("LIVE EXECUTION ALLOWED:", report.live_execution_allowed)
    print("AUTOMATIC RETRY ALLOWED:", report.automatic_retry_allowed)
    print("LIVE SHOPIFY WRITES: 0")
    print("PROJECT SQLITE WRITES: 0")
    if not report.can_continue_to_operator_review:
        print("STATUS: BLOCKED OR STALE — NO DISPATCH")
        return 2
    print("STATUS: READ-ONLY GATE VERIFIED — EXECUTION DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
