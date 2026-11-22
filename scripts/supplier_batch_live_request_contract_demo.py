"""Offline-only synthetic demo of V2.8B/1's request contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

# Allow direct execution: python scripts/supplier_batch_live_request_contract_demo.py
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from supplier.batch.live_request_contract import (
    CandidateQuantity,
    PreflightEvidence,
    prepare_mutation_preview,
)


def main() -> None:
    evidence = PreflightEvidence(
        plan_fingerprint="a" * 64,
        manifest_fingerprint="b" * 64,
        approved_manifest_fingerprint="b" * 64,
        preflight_fingerprint="c" * 64,
        status="READY",
        ready_items=2,
        stale_items=0,
        blocked_items=0,
    )
    items = (
        CandidateQuantity("DEMO-CAP", "gid://shopify/InventoryItem/1001", "gid://shopify/Location/100", 25, 25, 26),
        CandidateQuantity("DEMO-SHIRT", "gid://shopify/InventoryItem/1002", "gid://shopify/Location/100", 40, 40, 42),
    )
    preview = prepare_mutation_preview(evidence, items, operation_id=str(uuid4()))
    print("SHOPIFY AUTOMATION LAB — V2.8B/1 OFFLINE GRAPHQL CONTRACT")
    print("=" * 70)
    print("MODE:", preview.mode)
    print("CANDIDATES: SYNTHETIC — NOT REAL SHOPIFY INVENTORY")
    print("NETWORK CALLS: 0")
    print("SQLITE WRITES: 0")
    print("SHOPIFY WRITES: 0")
    print("\nMutation request structure (NOT SENT):")
    print(preview.query)
    print("\nGraphQL variables:")
    print(json.dumps(preview.variables, indent=2))
    print("\nSTATUS: CONTRACT BUILT — EXECUTION NOT ENABLED")


if __name__ == "__main__":
    main()
