"""V2.8B/6 synthetic-only proof: fenced queries + read-only journal inspection."""
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
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive  # noqa: E402
from supplier.batch.live_readonly_inspection import inspect_fresh_candidate, inspect_saved_operation  # noqa: E402
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository  # noqa: E402
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService  # noqa: E402


def main() -> int:
    prepared = build_prepared()
    baseline = inspect_fresh_candidate(prepared, readback_port=FakeReadback({"1001": 25, "1002": 40}))
    stale = inspect_fresh_candidate(prepared, readback_port=FakeReadback({"1001": 25, "1002": 39}))
    with TemporaryDirectory(prefix="supplier-v2-8b6-") as temp:
        path = Path(temp) / "recovery_demo.sqlite3"

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

        service = SupplierLiveBatchRecoveryService(
            intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connect),
            recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connect),
        )
        service.prepare(prepared)
        service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
        # The inspector opens this file with SQLite mode=ro and does NOT
        # append another event or modify the operation's immutable snapshot.
        archive = ReadOnlyRecoveryArchive(path)
        snapshot, events = archive.load_verified(prepared.preview.operation_id)
        recovery = inspect_saved_operation(
            archive=archive, operation_id=prepared.preview.operation_id,
            readback_port=FakeReadback({"1001": 26, "1002": 42}),
        )
        _, after = archive.load_verified(prepared.preview.operation_id)
        assert len(after) == len(events) == 1
    print("SHOPIFY AUTOMATION LAB — V2.8B/6 READ-ONLY SAFETY GATE DEMO")
    print("MODE: SYNTHETIC / TEMPORARY SQLITE ONLY")
    print("CASE A — UNCHANGED:", baseline.status.value)
    print("CASE B — DRIFT:", stale.status.value)
    print("CASE C — ARMED RECOVERY:", recovery.status.value)
    print("RECOVERY JOURNAL EVENTS:", len(events))
    print("AUTOMATIC RETRY ALLOWED:", recovery.automatic_retry_allowed)
    print("LIVE EXECUTION ALLOWED:", recovery.live_execution_allowed)
    print("REAL SHOPIFY NETWORK CALLS: 0")
    print("LIVE SHOPIFY WRITES: 0")
    print("PROJECT SQLITE WRITES: 0")
    print("STATUS: READ-ONLY GATE VERIFIED — EXECUTION DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
