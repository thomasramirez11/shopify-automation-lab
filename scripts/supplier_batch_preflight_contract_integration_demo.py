"""V2.8B/2 synthetic-only end-to-end integration; never contacts Shopify."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from supplier.batch.approval import evaluate_batch_approval  # noqa: E402
from supplier.batch.builder import build_batch_safety_manifest  # noqa: E402
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository  # noqa: E402
from supplier.batch.live_preflight_bridge import prepare_from_fresh_preflight  # noqa: E402
from supplier.batch.models import BatchSafetyPolicy  # noqa: E402
from supplier.decision.models import SupplierSyncDecision, SyncDecisionReason, SyncDecisionStatus  # noqa: E402
from supplier.execution.readback import InventoryReadbackState  # noqa: E402
from dataclasses import dataclass

@dataclass(frozen=True)
class ShopifyInventoryTarget:
    inventory_item_id: str
    location_id: str  # noqa: E402
from supplier.plan.builder import build_dry_run_sync_plan  # noqa: E402

LOCATION = "gid://shopify/Location/999001"


class FakeResolver:
    def resolve(self, shopify_variant_id):
        return ShopifyInventoryTarget(
            inventory_item_id="gid://shopify/InventoryItem/" + shopify_variant_id.rsplit("/", 1)[-1],
            location_id=LOCATION,
        )


class FakeReadback:
    def read_available(self, *, inventory_item_id, location_id):
        suffix = inventory_item_id.rsplit("/", 1)[-1]
        return InventoryReadbackState(
            inventory_item_id=inventory_item_id,
            sku=f"DEMO-{suffix}",
            tracked=True,
            location_id=location_id,
            location_name="Synthetic demo location",
            location_active=True,
            level_active=True,
            available_quantity={"1001": 25, "1002": 40}[suffix],
        )


def main() -> int:
    decisions = [
        SupplierSyncDecision(
            supplier_code="demo_supplier", supplier_sku=f"SUP-{suffix}",
            shopify_variant_id=f"gid://shopify/ProductVariant/{suffix}",
            shopify_sku=f"DEMO-{suffix}",
            status=SyncDecisionStatus.ELIGIBLE,
            reason=SyncDecisionReason.INVENTORY_MISMATCH_WITHIN_LIMIT,
            current_inventory_quantity=current,
            supplier_inventory_quantity=proposed,
            inventory_delta=proposed - current,
            proposed_inventory_quantity=proposed,
        )
        for suffix, current, proposed in (("1001", 25, 26), ("1002", 40, 42))
    ]
    plan = build_dry_run_sync_plan(decisions)
    manifest = build_batch_safety_manifest(plan=plan, policy=BatchSafetyPolicy())
    approval = evaluate_batch_approval(
        plan=plan, manifest=manifest,
        approved_manifest_fingerprint=manifest.manifest_fingerprint,
    )
    prepared = prepare_from_fresh_preflight(
        plan=plan, manifest=manifest, approval_report=approval,
        target_resolver=FakeResolver(), readback_port=FakeReadback(),
        expected_location_id=LOCATION,
    )

    with TemporaryDirectory(prefix="supplier-v2-8b2-") as temp:
        test_db = Path(temp) / "intents.sqlite3"

        @contextmanager
        def connection():
            db = sqlite3.connect(test_db)
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

        repository = SupplierLiveBatchIntentRepository(connection_factory=connection)
        intent = repository.reserve(prepared)
        replay = repository.reserve(prepared)
        assert intent == replay
        assert intent.status == "PREPARED"
        assert prepared.preflight.ready_items == 2
        assert prepared.preview.variables["idempotencyKey"] == intent.operation_id
        assert len(prepared.preview.variables["input"]["quantities"]) == 2
        assert all(
            item["changeFromQuantity"] is not None
            for item in prepared.preview.variables["input"]["quantities"]
        )

    print("SHOPIFY AUTOMATION LAB — V2.8B/2 TRUSTED PREFLIGHT BRIDGE DEMO")
    print("MODE: OFFLINE SYNTHETIC")
    print("PREFLIGHT STATUS: READY")
    print("CANDIDATES: 2")
    print("CAS VALUES: BOTH PRESENT")
    print("IDEMPOTENCY KEY: UUIDv4 GENERATED")
    print("APPEND-ONLY INTENT: PREPARED IN ISOLATED TEMPORARY DATABASE")
    print("REPLAY SAME OPERATION: IDEMPOTENT")
    print("REAL SHOPIFY NETWORK CALLS: 0")
    print("LIVE SHOPIFY WRITES: 0")
    print("PROJECT SQLITE WRITES: 0")
    print("STATUS: BRIDGE + INTENT VERIFIED — EXECUTION DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
