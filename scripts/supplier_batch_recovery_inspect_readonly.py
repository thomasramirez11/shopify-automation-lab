"""V2.8B/6 manually inspect one already-stored recovery operation (read-only).

This script NEVER creates/migrates any SQLite tables, never appends events,
and never submits a Shopify mutation. No project DB is accessed implicitly:
provide --database-file explicitly to inspect an existing recovery archive.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive  # noqa: E402
from supplier.batch.live_readonly_inspection import inspect_saved_operation  # noqa: E402
from supplier.batch.live_readonly_query_fence import ReadOnlyShopifyQueryFence  # noqa: E402
from supplier.batch.live_recovery_models import RecoveryConflict  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only recovery record + optional Shopify readback")
    parser.add_argument("--database-file", required=True, help="Existing SQLite recovery archive path")
    parser.add_argument("--operation-id", required=True, help="Previously saved operation UUIDv4")
    parser.add_argument("--read-shopify", action="store_true", help="Explicitly enable read-only Shopify queries")
    args = parser.parse_args(argv)
    print("SHOPIFY AUTOMATION LAB — V2.8B/6 RECOVERY INSPECTION")
    print("DB MODE: SQLITE READ ONLY | MUTATIONS: DISABLED | SQLITE WRITES: 0")
    try:
        archive = ReadOnlyRecoveryArchive(args.database_file)
        snapshot, events = archive.load_verified(args.operation_id)
    except (RecoveryConflict, OSError, ValueError):
        print("ARCHIVE: BLOCKED OR UNAVAILABLE")
        return 2
    print("OPERATION ID:", snapshot.operation_id)
    print("DISPATCH JOURNAL EVENTS:", len(events))
    print("INVENTORY READBACK ENABLED:", args.read_shopify)
    if not args.read_shopify:
        print("LIVE SHOPIFY NETWORK CALLS: 0")
        print("LIVE SHOPIFY WRITES: 0")
        print("STATUS: VERIFIED ARCHIVE — REAL READBACK NOT REQUESTED")
        return 0

    from scripts.supplier_live_batch_preflight import build_client
    from supplier.execution.readback import ShopifyInventoryReadbackAdapter
    try:
        client = ReadOnlyShopifyQueryFence(build_client())
        report = inspect_saved_operation(
            archive=archive, operation_id=args.operation_id,
            readback_port=ShopifyInventoryReadbackAdapter(client),
        )
    except Exception:
        print("STATUS: READBACK BLOCKED — HUMAN REVIEW REQUIRED")
        print("LIVE SHOPIFY WRITES: 0")
        return 2
    print("READBACK STATUS:", report.status.value)
    for item in report.items:
        print(f"  {item.sku}: {item.baseline} -> {item.proposed}; "
              f"observed={item.observed} classification={item.classification}")
    print("LIVE SHOPIFY INVENTORY READS:", client.read_queries)
    print("HUMAN REVIEW REQUIRED:", report.human_review_required)
    print("AUTOMATIC RETRY ALLOWED:", report.automatic_retry_allowed)
    print("LIVE EXECUTION ALLOWED:", report.live_execution_allowed)
    print("LIVE SHOPIFY WRITES: 0")
    print("SQLITE WRITES: 0")
    print("STATUS: READ-ONLY RECOVERY INSPECTED — EXECUTION DISABLED")
    return 0 if report.status.value != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
