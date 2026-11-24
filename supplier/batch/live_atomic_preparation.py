"""V2.8B/4 atomic preparation: one durable SQLite transaction for intent + request.

This repository has ZERO Shopify/network functionality. It never arms a dispatch.
Future execution MUST use the recovery service's separate dispatch guard and
still requires additional authorization, freshness and read-only reconciliation.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Callable, ContextManager

from supplier.batch.live_intent_repository import (
    SCHEMA_SQL as INTENT_SCHEMA_SQL,
    IntentConflict,
    SupplierLiveBatchIntentRepository,
)
from supplier.batch.live_preflight_bridge import PreparedBatchRequest
from supplier.batch.live_recovery_models import ImmutableRequestSnapshot, RecoveryConflict
from supplier.batch.live_recovery_repository import (
    RECOVERY_SCHEMA_SQL,
    SupplierLiveBatchRecoveryRepository,
    _canonical,
    _hash,
)


class SupplierLiveBatchAtomicPreparationRepository:
    """Safely stores intent and its exact payload on one injected SQLite database.

    The connection factory must implement a transaction context that commits
    on success and rolls back on exceptions (the existing V2 test factory does).
    Database initialization is completed BEFORE BEGIN IMMEDIATE because SQLite
    executescript() would otherwise commit an open transaction.
    """

    def __init__(self, *, connection_factory: Callable[[], ContextManager[sqlite3.Connection]]) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _initialize(db: sqlite3.Connection) -> None:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(INTENT_SCHEMA_SQL + RECOVERY_SCHEMA_SQL)
        if db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RecoveryConflict("SQLite foreign-key enforcement must be active")

    def prepare(self, prepared: PreparedBatchRequest) -> ImmutableRequestSnapshot:
        """Idempotent for identical unsent requests; no auto-repair of partial records.

        A failure after either INSERT but before COMMIT rolls back both records.
        A replay with an existing dispatch event is rejected, not reauthorized.
        """
        # Validate *before* acquiring the database lock. The same canonical
        # validation is used by the legacy intent ledger to prevent drift.
        SupplierLiveBatchIntentRepository.validate_prepared(prepared)
        payload = SupplierLiveBatchRecoveryRepository._make_payload(prepared)
        encoded = _canonical(payload)
        sha = _hash(encoded)
        op = prepared.preview.operation_id
        intent_record = (
            op, prepared.batch_id, prepared.plan_fingerprint,
            prepared.manifest_fingerprint, prepared.preflight_fingerprint,
            prepared.location_id, prepared.request_digest, "PREPARED",
        )
        snapshot_record = (prepared.request_digest, encoded, sha)
        with self._connection_factory() as db:
            self._initialize(db)
            db.execute("BEGIN IMMEDIATE")
            # Treat an existing manifest as consumed: it cannot be used again
            # with a new operation UUID, even if values have not changed.
            existing = db.execute("""SELECT operation_id, batch_id, plan_fingerprint,
                manifest_fingerprint, preflight_fingerprint, location_id,
                request_digest, status FROM supplier_live_batch_intents
                WHERE operation_id=? OR (manifest_fingerprint=? AND location_id=?)""", (
                    op, prepared.manifest_fingerprint, prepared.location_id,
            )).fetchone()
            if existing is not None and tuple(existing) != intent_record:
                raise IntentConflict("manifest/location or operation ID already reserved for another request")
            if existing is None:
                db.execute("""INSERT INTO supplier_live_batch_intents (
                    operation_id, batch_id, plan_fingerprint, manifest_fingerprint,
                    preflight_fingerprint, location_id, request_digest, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", intent_record)

            # Bind the full nested GraphQL request to the EXACT immutable intent,
            # including the CAS baseline and Shopify idempotency key.
            intent = SupplierLiveBatchRecoveryRepository._get_intent(db, op)
            SupplierLiveBatchRecoveryRepository._validate_payload(payload, intent)
            prior = db.execute("""SELECT request_digest, payload_json, payload_sha256
                FROM supplier_live_batch_request_snapshots WHERE operation_id=?""", (op,)).fetchone()
            if existing is not None and prior is None:
                # If a previous buggy version reserved intent without snapshot,
                # require an operator to investigate rather than repairing it.
                raise RecoveryConflict("partial pre-existing intent: manual review required; no automatic repair")
            if prior is None:
                db.execute("""INSERT INTO supplier_live_batch_request_snapshots
                    (operation_id, request_digest, payload_json, payload_sha256)
                    VALUES (?, ?, ?, ?)""", (op, *snapshot_record))
            elif tuple(prior) != snapshot_record:
                raise RecoveryConflict("immutable snapshot differs from the previously reserved request")
            if existing is not None:
                # Replaying preparation is never a second dispatch authorization.
                events = SupplierLiveBatchRecoveryRepository._read_events(db, op)
                if events:
                    raise RecoveryConflict("operation has a dispatch history; preparation replay blocked")

        return ImmutableRequestSnapshot(op, prepared.request_digest, sha, json.loads(encoded))
