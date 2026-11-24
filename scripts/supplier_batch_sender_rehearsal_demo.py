"""V2.8B/8: fake-only end-to-end rehearsal of operator review -> send -> readback.

The test creates separate temporary SQLite files per scenario. No real Shopify
client, API tokens, live mutation transport, or project SQLite database is used.
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

from scripts.supplier_batch_recovery_synthetic_demo import FakeReadback, build_prepared  # noqa: E402
from scripts.supplier_batch_fake_sender_checkpoint_demo import acknowledged, rejected  # noqa: E402
from supplier.batch.live_fake_receipt_repository import SupplierLiveBatchFakeReceiptRepository  # noqa: E402
from supplier.batch.live_fake_sender import ScriptedFakeShopifyTransport, SupplierLiveBatchFakeSender  # noqa: E402
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository  # noqa: E402
from supplier.batch.live_operator_review import review_saved_batch  # noqa: E402
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive  # noqa: E402
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository  # noqa: E402
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService  # noqa: E402
from supplier.batch.live_sender_rehearsal import SupplierBatchSenderRehearsal  # noqa: E402


def exercise(folder: Path, name: str, scripted_response, *, stale: bool = False,
             wrong_fingerprint: bool = False, readback: bool = False) -> None:
    path = folder / (name.lower() + ".sqlite3")

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

    prepared = build_prepared()
    service = SupplierLiveBatchRecoveryService(
        intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connect),
        recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connect),
    )
    service.prepare(prepared)
    archive = ReadOnlyRecoveryArchive(path)
    review_options = {
        "archive": archive,
        "operation_id": prepared.preview.operation_id,
        "expected_plan_fingerprint": prepared.plan_fingerprint,
        "expected_manifest_fingerprint": prepared.manifest_fingerprint,
        "expected_location_id": prepared.location_id,
    }
    baseline = FakeReadback({"1001": 25, "1002": 40})
    first_review = review_saved_batch(**review_options, readback_port=baseline)
    assert first_review.review_fingerprint is not None
    expected_fingerprint = "f" * 64 if wrong_fingerprint else first_review.review_fingerprint
    transport = ScriptedFakeShopifyTransport(
        scripted_response(prepared) if callable(scripted_response) else scripted_response,
    )
    runner = SupplierBatchSenderRehearsal(
        archive=archive,
        fake_sender=SupplierLiveBatchFakeSender(
            recovery_service=service,
            receipt_repository=SupplierLiveBatchFakeReceiptRepository(connection_factory=connect),
        ),
    )
    options = {k: v for k, v in review_options.items() if k != "archive"}
    result = runner.run_once(
        **options,
        expected_review_fingerprint=expected_fingerprint,
        readback_port=FakeReadback({"1001": 25, "1002": 39 if stale else 40}),
        transport=transport,
        post_send_readback_port=FakeReadback({"1001": 26, "1002": 42}) if readback else None,
    )
    decision = service.decision(operation_id=prepared.preview.operation_id)
    assert not decision.automatic_retry_allowed
    print(f"CASE {name}: {result.status.value}")
    print(f"  FAKE SEND CALLS: {transport.calls}")
    print(f"  JOURNAL EVENTS: {decision.event_count}")
    print(f"  RECOVERY STATE: {decision.state.value}")
    print(f"  AUTO RETRY ALLOWED: {decision.automatic_retry_allowed}")


def main() -> int:
    print("SHOPIFY AUTOMATION LAB — V2.8B/8 COMPOSED SENDER REHEARSAL")
    print("MODE: OFFLINE ONLY / FAKE TRANSPORT / TEMPORARY SQLITE")
    with TemporaryDirectory(prefix="shopify-v2-8b8-") as directory:
        folder = Path(directory)
        exercise(folder, "ACK_WITH_FAKE_READBACK", acknowledged, readback=True)
        exercise(folder, "USER_ERRORS", rejected)
        exercise(folder, "TIMEOUT", TimeoutError("simulated no-response"))
        exercise(folder, "DRIFT", acknowledged, stale=True)
        exercise(folder, "FINGERPRINT_MISMATCH", acknowledged, wrong_fingerprint=True)
    print("REAL SHOPIFY NETWORK CALLS: 0")
    print("LIVE SHOPIFY WRITES: 0")
    print("PROJECT SQLITE WRITES: 0")
    print("STATUS: COMPOSED SENDER REHEARSAL VERIFIED — LIVE SENDER DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
