"""V2.8B/5: append-only *synthetic* mutation response evidence.

Receipts belong to a fake transport exercise. They do not mark inventory
verified or authorize live dispatch, and contain no raw Shopify responses.
"""

from __future__ import annotations

import sqlite3
import re
from dataclasses import dataclass
from typing import Callable, ContextManager

from supplier.batch.live_recovery_models import RecoveryConflict, RecoveryEventKind
from supplier.batch.live_recovery_repository import (
    SupplierLiveBatchRecoveryRepository, _canonical, _hash,
)
from supplier.batch.live_response_policy import ResponseAssessment, SimulatedResponseStatus


REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,71}$")

FAKE_RECEIPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS supplier_live_batch_fake_receipts (
    operation_id TEXT PRIMARY KEY,
    request_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(operation_id) REFERENCES supplier_live_batch_intents(operation_id)
);
CREATE TRIGGER IF NOT EXISTS trg_supplier_fake_receipts_no_update
BEFORE UPDATE ON supplier_live_batch_fake_receipts BEGIN
    SELECT RAISE(ABORT, 'fake receipts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_supplier_fake_receipts_no_delete
BEFORE DELETE ON supplier_live_batch_fake_receipts BEGIN
    SELECT RAISE(ABORT, 'fake receipts are append-only');
END;
"""


@dataclass(frozen=True, slots=True)
class FakeResponseReceipt:
    operation_id: str
    request_digest: str
    status: SimulatedResponseStatus
    reason_code: str
    receipt_sha256: str


def _receipt_hash(operation_id: str, request_digest: str, status: str, reason: str) -> str:
    return _hash(_canonical({
        "operation_id": operation_id,
        "request_digest": request_digest,
        "status": status,
        "reason_code": reason,
    }))


class SupplierLiveBatchFakeReceiptRepository:
    def __init__(self, *, connection_factory: Callable[[], ContextManager[sqlite3.Connection]]) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _initialize(db: sqlite3.Connection) -> None:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(FAKE_RECEIPT_SCHEMA)

    def record(self, *, recovery_repository: SupplierLiveBatchRecoveryRepository,
               operation_id: str, assessment: ResponseAssessment) -> FakeResponseReceipt:
        if not isinstance(assessment, ResponseAssessment) or not isinstance(assessment.status, SimulatedResponseStatus):
            raise RecoveryConflict("invalid fake response assessment")
        if assessment.automatic_retry_allowed or assessment.inventory_verified:
            raise RecoveryConflict("fake response must never permit retries or mark inventory verified")
        if not isinstance(assessment.reason_code, str) or not REASON_CODE_RE.fullmatch(assessment.reason_code):
            raise RecoveryConflict("unsafe fake response reason code")
        snapshot = recovery_repository.load_snapshot(operation_id)
        events = recovery_repository.events(operation_id)
        if not events or events[0].kind != RecoveryEventKind.DISPATCH_ARMED:
            raise RecoveryConflict("fake receipt requires a prior durable dispatch-arm journal event")
        receipt_sha = _receipt_hash(operation_id, snapshot.request_digest, assessment.status.value, assessment.reason_code)
        with self._connection_factory() as db:
            self._initialize(db)
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT operation_id, request_digest, status, reason_code, receipt_sha256
                FROM supplier_live_batch_fake_receipts WHERE operation_id=?""", (operation_id,)).fetchone()
            expected = (operation_id, snapshot.request_digest, assessment.status.value, assessment.reason_code, receipt_sha)
            if row is None:
                db.execute("""INSERT INTO supplier_live_batch_fake_receipts
                    (operation_id, request_digest, status, reason_code, receipt_sha256)
                    VALUES (?, ?, ?, ?, ?)""", expected)
            elif tuple(row) != expected:
                raise RecoveryConflict("fake receipt conflict; a different response was already recorded")
        return FakeResponseReceipt(operation_id, snapshot.request_digest, assessment.status,
                                   assessment.reason_code, receipt_sha)

    def load(self, *, recovery_repository: SupplierLiveBatchRecoveryRepository, operation_id: str) -> FakeResponseReceipt:
        snapshot = recovery_repository.load_snapshot(operation_id)
        with self._connection_factory() as db:
            self._initialize(db)
            row = db.execute("""SELECT operation_id, request_digest, status, reason_code, receipt_sha256
                FROM supplier_live_batch_fake_receipts WHERE operation_id=?""", (operation_id,)).fetchone()
        if row is None:
            raise RecoveryConflict("fake receipt not found")
        op, digest, status, reason, receipt_sha = tuple(row)
        try:
            kind = SimulatedResponseStatus(status)
        except ValueError as exc:
            raise RecoveryConflict("unknown fake receipt status") from exc
        if (op != operation_id or digest != snapshot.request_digest
                or receipt_sha != _receipt_hash(op, digest, status, reason)):
            raise RecoveryConflict("fake receipt integrity check failed")
        return FakeResponseReceipt(op, digest, kind, reason, receipt_sha)
