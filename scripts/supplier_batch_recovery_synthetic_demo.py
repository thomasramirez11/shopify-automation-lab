"""V2.8B/3 fake crash/restart test. No real Shopify network, no production DB."""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supplier.batch.approval import evaluate_batch_approval  # noqa: E402
from supplier.batch.builder import build_batch_safety_manifest  # noqa: E402
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository  # noqa: E402
from supplier.batch.live_preflight_bridge import prepare_from_fresh_preflight  # noqa: E402
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository  # noqa: E402
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService  # noqa: E402
from supplier.batch.models import BatchSafetyPolicy  # noqa: E402
from supplier.decision.models import SupplierSyncDecision, SyncDecisionReason, SyncDecisionStatus  # noqa: E402
from supplier.execution.readback import InventoryReadbackState  # noqa: E402
from supplier.plan.builder import build_dry_run_sync_plan  # noqa: E402

LOCATION = "gid://shopify/Location/999001"


@dataclass(frozen=True)
class FakeTarget:
    inventory_item_id: str
    location_id: str


class FakeResolver:
    def resolve(self, variant_id: str):
        return FakeTarget(
            inventory_item_id="gid://shopify/InventoryItem/" + variant_id.rsplit("/", 1)[-1],
            location_id=LOCATION,
        )


class FakeReadback:
    def __init__(self, quantities: dict[str, int]) -> None:
        self.quantities = quantities

    def read_available(self, *, inventory_item_id: str, location_id: str):
        suffix = inventory_item_id.rsplit("/", 1)[-1]
        return InventoryReadbackState(
            inventory_item_id=inventory_item_id, sku=f"DEMO-{suffix}", tracked=True,
            location_id=location_id, location_name="Synthetic location",
            location_active=True, level_active=True,
            available_quantity=self.quantities[suffix],
        )


def build_prepared():
    decisions = [
        SupplierSyncDecision(
            supplier_code="demo_supplier", supplier_sku=f"SUP-{suffix}",
            shopify_variant_id=f"gid://shopify/ProductVariant/{suffix}",
            shopify_sku=f"DEMO-{suffix}", status=SyncDecisionStatus.ELIGIBLE,
            reason=SyncDecisionReason.INVENTORY_MISMATCH_WITHIN_LIMIT,
            current_inventory_quantity=baseline,
            supplier_inventory_quantity=target,
            inventory_delta=target - baseline,
            proposed_inventory_quantity=target,
        )
        for suffix, baseline, target in (("1001", 25, 26), ("1002", 40, 42))
    ]
    plan = build_dry_run_sync_plan(decisions)
    manifest = build_batch_safety_manifest(plan=plan, policy=BatchSafetyPolicy())
    approval = evaluate_batch_approval(
        plan=plan, manifest=manifest,
        approved_manifest_fingerprint=manifest.manifest_fingerprint,
    )
    return prepare_from_fresh_preflight(
        plan=plan, manifest=manifest, approval_report=approval,
        target_resolver=FakeResolver(),
        readback_port=FakeReadback({"1001": 25, "1002": 40}),
        expected_location_id=LOCATION,
    )


def main() -> int:
    prepared = build_prepared()
    with TemporaryDirectory(prefix="supplier-v2-8b3-") as directory:
        db_path = Path(directory) / "isolated_recovery.sqlite3"

        @contextmanager
        def connection():
            db = sqlite3.connect(db_path)
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

        def make_service():
            return SupplierLiveBatchRecoveryService(
                intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connection),
                recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connection),
            )

        service = make_service()
        service.prepare(prepared)
        initial = service.decision(operation_id=prepared.preview.operation_id)
        assert initial.state.value == "PREPARED_NOT_SENT"
        service.arm_dispatch(
            operation_id=prepared.preview.operation_id,
            request_digest=prepared.request_digest,
        )
        # Simulate termination immediately after committing the pre-send event.
        del service
        restarted = make_service()
        after_restart = restarted.decision(operation_id=prepared.preview.operation_id)
        assert after_restart.state.value == "ARMED_OUTCOME_UNCERTAIN"
        assert not after_restart.automatic_retry_allowed
        restarted.note_outcome_unknown(operation_id=prepared.preview.operation_id)
        # Fake store state after ambiguous delivery. Real Shopify was NEVER touched.
        restarted.observe_current_inventory(
            operation_id=prepared.preview.operation_id,
            readback_port=FakeReadback({"1001": 26, "1002": 42}),
        )
        observed = restarted.decision(operation_id=prepared.preview.operation_id)
        assert observed.state.value == "READBACK_TARGET_OBSERVED"
        assert not observed.dispatch_allowed and not observed.automatic_retry_allowed
        print("SHOPIFY AUTOMATION LAB — V2.8B/3 CRASH/RESTART RECOVERY DEMO")
        print("MODE: ISOLATED SQLITE + SYNTHETIC SHOPIFY READBACK")
        print("START:", initial.state.value)
        print("AFTER SIMULATED CRASH:", after_restart.state.value)
        print("AFTER FAKE READBACK:", observed.state.value)
        print("AUTOMATIC RETRY ALLOWED:", observed.automatic_retry_allowed)
        print("HUMAN REVIEW REQUIRED:", observed.human_review_required)
        print("JOURNAL EVENTS:", observed.event_count)
        print("REAL SHOPIFY NETWORK CALLS: 0")
        print("LIVE SHOPIFY WRITES: 0")
        print("PROJECT SQLITE WRITES: 0")
        print("STATUS: RECOVERY CHECKPOINT VERIFIED — EXECUTION DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
