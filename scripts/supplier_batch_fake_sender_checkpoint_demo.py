"""V2.8B/5: scripted responses only. No network or real project DB."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.supplier_batch_recovery_synthetic_demo import build_prepared  # noqa: E402
from supplier.batch.live_fake_receipt_repository import SupplierLiveBatchFakeReceiptRepository  # noqa: E402
from supplier.batch.live_fake_sender import ScriptedFakeShopifyTransport, SupplierLiveBatchFakeSender  # noqa: E402
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository  # noqa: E402
from supplier.batch.live_recovery_models import RecoveryConflict  # noqa: E402
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository  # noqa: E402
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService  # noqa: E402


def run_scenario(folder: Path, name: str, scripted_response) -> None:
    path = folder / f"{name}.sqlite3"

    @contextmanager
    def connect():
        db = sqlite3.connect(path)
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
            intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connect),
            recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connect),
        )

    prepared = build_prepared()
    make_service().prepare(prepared)
    adapter = ScriptedFakeShopifyTransport(scripted_response(prepared) if callable(scripted_response) else scripted_response)
    sender = SupplierLiveBatchFakeSender(
        recovery_service=make_service(),
        receipt_repository=SupplierLiveBatchFakeReceiptRepository(connection_factory=connect),
    )
    result = sender.send_once(operation_id=prepared.preview.operation_id, transport=adapter)
    restarted = make_service()
    decision = restarted.decision(operation_id=prepared.preview.operation_id)
    saved_receipt = SupplierLiveBatchFakeReceiptRepository(connection_factory=connect).load(
        recovery_repository=restarted._recovery, operation_id=prepared.preview.operation_id,
    )
    assert saved_receipt == result.receipt
    assert decision.automatic_retry_allowed is False
    try:
        sender.send_once(operation_id=prepared.preview.operation_id, transport=adapter)
    except RecoveryConflict:
        replay = "BLOCKED"
    else:
        raise AssertionError("replay was not blocked")
    with connect() as db:
        event_count = db.execute("SELECT COUNT(*) FROM supplier_live_batch_dispatch_events").fetchone()[0]
        receipt_count = db.execute("SELECT COUNT(*) FROM supplier_live_batch_fake_receipts").fetchone()[0]
    print(f"CASE {name}")
    print("  RESPONSE:", result.assessment.status.value)
    print("  REASON CODE:", result.assessment.reason_code)
    print("  JOURNAL EVENTS:", event_count)
    print("  PERSISTED FAKE RECEIPTS:", receipt_count)
    print("  FAKE SEND CALLS:", adapter.calls)
    print("  RESTART STATE:", decision.state.value)
    print("  REPLAY:", replay)
    print("  AUTOMATIC RETRY ALLOWED:", decision.automatic_retry_allowed)
    print("  INVENTORY VERIFIED BY MUTATION RESPONSE:", result.assessment.inventory_verified)


def acknowledged(prepared):
    return {
        "data": {
            "inventorySetQuantities": {
                "userErrors": [],
                "inventoryAdjustmentGroup": {
                    "reason": "Inventory correction",
                    "referenceDocumentUri": prepared.preview.variables["input"]["referenceDocumentUri"],
                    "changes": [
                        {"name": "available", "delta": 1, "quantityAfterChange": None},
                        {"name": "on_hand", "delta": 1, "quantityAfterChange": None},
                        {"name": "available", "delta": 2, "quantityAfterChange": None},
                    ],
                },
            }
        }
    }


def rejected(_prepared):
    return {"data": {"inventorySetQuantities": {
        "userErrors": [{"code": "INVALID_QUANTITY", "message": "Simulated rejected mutation", "field": ["input"]}],
        "inventoryAdjustmentGroup": None,
    }}}


def main() -> int:
    with TemporaryDirectory(prefix="supplier-v2-8b5-") as directory:
        root = Path(directory)
        print("SHOPIFY AUTOMATION LAB — V2.8B/5 FAKE SHOPIFY MUTATION SENDER")
        print("MODE: SCRIPTED FAKE TRANSPORT + ISOLATED TEMPORARY SQLITE")
        run_scenario(root, "ACK", acknowledged)
        run_scenario(root, "USER_ERRORS", rejected)
        run_scenario(root, "TIMEOUT", TimeoutError("simulated timeout; not recorded"))
        print("REAL SHOPIFY NETWORK CALLS: 0")
        print("LIVE SHOPIFY WRITES: 0")
        print("PROJECT SQLITE WRITES: 0")
        print("STATUS: FAKE SENDER VERIFIED — LIVE EXECUTION DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
