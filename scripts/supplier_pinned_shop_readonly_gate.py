"""V2.8B/11 — REAL Shopify shop-bound inventory inspection. READ ONLY.

No mutations, no durable intent, no dispatch, no SQLite writes. The input
candidate is synthetic, using the trusted V1 snapshot (+1 / +2 quantities).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supplier.batch.approval import evaluate_batch_approval  # noqa: E402
from supplier.batch.live_pinned_readonly_controller import (  # noqa: E402
    PinnedReadOnlyStatus, inspect_pinned_live_candidate,
)
from supplier.batch.live_request_contract import LOCATION_GID_RE  # noqa: E402
from supplier.batch.live_store_identity import SHOP_GID_RE  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pinned Shopify shop + inventory READ-ONLY gate")
    parser.add_argument("--expected-shop-id", required=True, help="Shop GID verified independently")
    parser.add_argument("--location-id", required=True, help="Shopify Location GID")
    parser.add_argument("--approve-manifest", default=None, help="Exact current manifest fingerprint")
    args = parser.parse_args(argv)
    if SHOP_GID_RE.fullmatch(args.expected_shop_id) is None:
        parser.error("expected-shop-id must be a Shopify Shop GID")
    if LOCATION_GID_RE.fullmatch(args.location_id) is None:
        parser.error("location-id must be a Shopify Location GID")

    from scripts.supplier_live_batch_preflight import build_read_only_candidate, build_client
    from supplier.execution.shopify_adapter import SQLiteInventoryTargetResolver

    print("SHOPIFY AUTOMATION LAB — V2.8B/11 SHOP-PINNED READ-ONLY GATE")
    print("CANDIDATE: TRUSTED V1 SQLITE BASELINE + SYNTHETIC PROPOSALS")
    print("MODE: READ ONLY | NO MUTATION | NO PROJECT SQLITE WRITES")
    plan, manifest = build_read_only_candidate()
    approval = evaluate_batch_approval(
        plan=plan, manifest=manifest,
        approved_manifest_fingerprint=args.approve_manifest,
    )
    print("MANIFEST FINGERPRINT:", manifest.manifest_fingerprint)
    print("APPROVAL STATUS:", approval.status.value.upper())
    if not approval.can_execute:
        print("SHOP IDENTITY QUERIES: 0")
        print("LIVE INVENTORY READS: 0")
        print("LIVE SHOPIFY WRITES: 0")
        print("RE-RUN WITH --approve-manifest", manifest.manifest_fingerprint)
        return 0
    try:
        report = inspect_pinned_live_candidate(
            client=build_client(), expected_shop_id=args.expected_shop_id,
            expected_location_id=args.location_id,
            plan=plan, manifest=manifest, approval_report=approval,
            target_resolver=SQLiteInventoryTargetResolver(location_id=args.location_id),
        )
    except Exception:
        print("STATUS: BLOCKED — AUTHENTICATED SHOPIFY REVIEW UNAVAILABLE")
        print("LIVE SHOPIFY WRITES: 0")
        return 2

    print("STATUS:", report.status.value)
    print("AUTHENTICATED SHOP ID:", report.shop_id or "BLOCKED")
    print("SHOP DOMAIN:", report.shop_domain or "BLOCKED")
    print("SHOP IDENTITY QUERIES:", report.shop_identity_reads)
    print("LIVE INVENTORY READS:", report.inventory_reads)
    for sku, baseline, observed, proposed in report.inspected_items:
        print(f"  {sku}: baseline={baseline} observed={observed} synthetic_proposed={proposed}")
    if report.inspection_fingerprint:
        print("READ-ONLY REVIEW FINGERPRINT:", report.inspection_fingerprint)
    print("CAN CONTINUE TO OPERATOR REVIEW:", report.can_continue_to_operator_review)
    print("LIVE EXECUTION ALLOWED:", report.live_execution_allowed)
    print("AUTOMATIC RETRY ALLOWED:", report.automatic_retry_allowed)
    print("OPERATOR AUTHENTICATED:", report.operator_authenticated)
    print("LIVE SHOPIFY WRITES: 0")
    print("PROJECT SQLITE WRITES: 0")
    if report.status is not PinnedReadOnlyStatus.BASELINES_MATCH:
        print("RESULT: BLOCKED — NO DISPATCH")
        return 2
    print("RESULT: PINNED SHOP + FOUR INVENTORY READS VERIFIED — EXECUTION DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
