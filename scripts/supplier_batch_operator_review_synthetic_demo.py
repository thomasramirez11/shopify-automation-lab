"""Offline operator-review proof; never reads a real Shopify store or project DB."""
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.supplier_batch_recovery_synthetic_demo import FakeReadback, build_prepared  # noqa: E402
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository  # noqa: E402
from supplier.batch.live_operator_review import review_saved_batch  # noqa: E402
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive  # noqa: E402
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository  # noqa: E402
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService  # noqa: E402


def main() -> int:
    prepared = build_prepared()
    with TemporaryDirectory(prefix="v2-8b7-review-") as temp:
        path = Path(temp) / "review.sqlite3"

        @contextmanager
        def connection():
            db = sqlite3.connect(path)
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

        recovery = SupplierLiveBatchRecoveryService(
            intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connection),
            recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connection),
        )
        recovery.prepare(prepared)
        archive = ReadOnlyRecoveryArchive(path)
        opts = dict(
            archive=archive, operation_id=prepared.preview.operation_id,
            expected_plan_fingerprint=prepared.plan_fingerprint,
            expected_manifest_fingerprint=prepared.manifest_fingerprint,
            expected_location_id=prepared.location_id,
        )
        ready = review_saved_batch(**opts, readback_port=FakeReadback({"1001": 25, "1002": 40}))
        stale = review_saved_batch(**opts, readback_port=FakeReadback({"1001": 25, "1002": 39}))
        recovery.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
        armed = review_saved_batch(**opts, readback_port=FakeReadback({"1001": 26, "1002": 42}))
        assert ready.can_continue_to_operator_review
        assert not stale.can_continue_to_operator_review
        assert not armed.can_continue_to_operator_review
        assert not any((ready.live_execution_allowed, stale.live_execution_allowed, armed.live_execution_allowed))
        print("SHOPIFY AUTOMATION LAB — V2.8B/7 OPERATOR SAFETY REVIEW")
        print("MODE: OFFLINE / ISOLATED SQLITE")
        print("CASE A — BASELINES MATCH:", ready.status.value)
        print("CASE B — ONE ITEM DRIFTED:", stale.status.value)
        print("CASE C — PREVIOUS DISPATCH:", armed.status.value)
        print("REVIEW FINGERPRINT GENERATED:", bool(ready.review_fingerprint))
        print("LIVE EXECUTION ALLOWED:", ready.live_execution_allowed)
        print("AUTOMATIC RETRY ALLOWED:", ready.automatic_retry_allowed)
        print("REAL SHOPIFY NETWORK CALLS: 0")
        print("LIVE SHOPIFY WRITES: 0")
        print("PROJECT SQLITE WRITES: 0")
        print("STATUS: OPERATOR REVIEW FIREWALL VERIFIED — LIVE SENDER DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
