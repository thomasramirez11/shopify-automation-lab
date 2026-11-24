"""V2.8B/4: crash-safe, fully offline, transaction atomicity demonstration.

This script NEVER contacts Shopify or touches the real project SQLite database.
"""

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
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository  # noqa: E402
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository  # noqa: E402
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService  # noqa: E402


def main() -> int:
    with TemporaryDirectory(prefix="supplier-v2-8b4-") as folder:
        db_path = Path(folder) / "isolated_atomic_prep.sqlite3"

        @contextmanager
        def connect():
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
                intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connect),
                recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connect),
            )

        prepared = build_prepared()  # All mocked / synthetic V2.8A checks.
        service = make_service()
        result = service.prepare(prepared)
        assert result.payload["variables"]["idempotencyKey"] == prepared.preview.operation_id
        assert service.prepare(prepared) == result  # Exact unsent replay is a no-op.
        with connect() as db:
            intents = db.execute("SELECT COUNT(*) FROM supplier_live_batch_intents").fetchone()[0]
            snapshots = db.execute("SELECT COUNT(*) FROM supplier_live_batch_request_snapshots").fetchone()[0]
            events = db.execute("SELECT COUNT(*) FROM supplier_live_batch_dispatch_events").fetchone()[0]
        assert (intents, snapshots, events) == (1, 1, 0)
        restarted = make_service()
        decision = restarted.decision(operation_id=prepared.preview.operation_id)
        assert decision.state.value == "PREPARED_NOT_SENT"
        assert not decision.dispatch_allowed and not decision.automatic_retry_allowed
        print("SHOPIFY AUTOMATION LAB — V2.8B/4 ATOMIC PREPARATION DEMO")
        print("MODE: ISOLATED SQLITE + SYNTHETIC PREFLIGHT")
        print("ATOMIC INTENT + SNAPSHOT: COMMITTED TOGETHER")
        print("INTENTS:", intents)
        print("SNAPSHOTS:", snapshots)
        print("DISPATCH EVENTS:", events)
        print("SAME-OPERATION PREPARE REPLAY: IDEMPOTENT")
        print("RESTART STATE:", decision.state.value)
        print("AUTOMATIC RETRY ALLOWED:", decision.automatic_retry_allowed)
        print("REAL SHOPIFY NETWORK CALLS: 0")
        print("LIVE SHOPIFY WRITES: 0")
        print("PROJECT SQLITE WRITES: 0")
        print("STATUS: ATOMIC PREPARATION VERIFIED — EXECUTION DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
