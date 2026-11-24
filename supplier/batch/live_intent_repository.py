"""V2.8B/2: append-only intent ledger for a future two-item Shopify batch.

No Shopify networking. No recovery/resend implementation. PREPARED is NOT SENT.
Inject a connection factory; tests/demos use isolated databases, never the V1 DB.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, ContextManager
from uuid import UUID

from supplier.batch.live_preflight_bridge import (
    PreparedBatchRequest,
    calculate_request_digest,
)
from supplier.batch.live_request_contract import (
    CandidateQuantity,
    ContractRejected,
    INVENTORY_SET_QUANTITIES,
    PreflightEvidence,
    prepare_mutation_preview,
)
from supplier.preflight.models import BatchPreflightItemStatus, BatchPreflightStatus


class IntentConflict(ValueError):
    """A manifest or operation identity was already reserved differently."""


@dataclass(frozen=True, slots=True)
class StoredIntent:
    operation_id: str
    batch_id: str
    manifest_fingerprint: str
    preflight_fingerprint: str
    request_digest: str
    status: str


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS supplier_live_batch_intents (
    operation_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    plan_fingerprint TEXT NOT NULL,
    manifest_fingerprint TEXT NOT NULL,
    preflight_fingerprint TEXT NOT NULL,
    location_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'PREPARED'),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (manifest_fingerprint, location_id)
);
CREATE TRIGGER IF NOT EXISTS trg_supplier_live_batch_intents_no_update
BEFORE UPDATE ON supplier_live_batch_intents BEGIN
    SELECT RAISE(ABORT, 'live batch intents are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_supplier_live_batch_intents_no_delete
BEFORE DELETE ON supplier_live_batch_intents BEGIN
    SELECT RAISE(ABORT, 'live batch intents are append-only');
END;
"""


class SupplierLiveBatchIntentRepository:
    def __init__(self, *, connection_factory: Callable[[], ContextManager[sqlite3.Connection]]) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def validate_prepared(prepared: PreparedBatchRequest) -> None:
        """Validate preflight, payload, identity, CAS and digest without database writes.

        Also used by V2.8B/4 atomic preparation so validation stays in one place.
        """
        if not isinstance(prepared, PreparedBatchRequest):
            raise IntentConflict("expected a PreparedBatchRequest")
        try:
            uid = UUID(prepared.preview.operation_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise IntentConflict("invalid operation id") from exc
        if str(uid) != prepared.preview.operation_id or uid.version != 4:
            raise IntentConflict("operation id must be UUIDv4")
        for name in ("batch_id", "plan_fingerprint", "manifest_fingerprint", "preflight_fingerprint", "request_digest"):
            if not isinstance(getattr(prepared, name), str) or not re.fullmatch("[a-f0-9]{64}", getattr(prepared, name)):
                raise IntentConflict(f"invalid {name}")
        if not isinstance(prepared.location_id, str) or not re.fullmatch(r"gid://shopify/Location/[1-9][0-9]*", prepared.location_id):
            raise IntentConflict("invalid location id")
        if prepared.mode != "OFFLINE_PREVIEW_ONLY" or prepared.preview.mode != "OFFLINE_PREVIEW_ONLY":
            raise IntentConflict("only offline previews may be reserved at this checkpoint")

        # Reject changes to a frozen dataclass's nested (mutable) variables dict.
        report = prepared.preflight
        if (
            report.status != BatchPreflightStatus.READY
            or (report.ready_items, report.stale_items, report.blocked_items) != (2, 0, 0)
            or len(report.items) != 2
            or report.source_plan_fingerprint != prepared.plan_fingerprint
            or report.manifest_fingerprint != prepared.manifest_fingerprint
            or report.approved_manifest_fingerprint != prepared.manifest_fingerprint
            or report.preflight_fingerprint != prepared.preflight_fingerprint
            or report.location_id != prepared.location_id
        ):
            raise IntentConflict("preflight evidence is not bound to the prepared request")
        expected_batch_id = hashlib.sha256(
            ("supplier-batch:" + prepared.manifest_fingerprint).encode("utf-8")
        ).hexdigest()
        if prepared.batch_id != expected_batch_id:
            raise IntentConflict("batch audit identity mismatch")
        try:
            evidence = PreflightEvidence(
                prepared.plan_fingerprint, prepared.manifest_fingerprint,
                prepared.manifest_fingerprint, prepared.preflight_fingerprint,
                "READY", 2, 0, 0,
            )
            candidates = tuple(
                CandidateQuantity(
                    item.shopify_sku, item.inventory_item_id, item.location_id,
                    item.approved_baseline_quantity, item.fresh_shopify_quantity,
                    item.proposed_inventory_quantity,
                )
                for item in report.items
                if item.status == BatchPreflightItemStatus.READY
                and item.location_id == prepared.location_id
            )
            canonical_preview = prepare_mutation_preview(
                evidence, candidates, operation_id=prepared.preview.operation_id,
            )
        except (ContractRejected, TypeError, AttributeError) as exc:
            raise IntentConflict("prepared request no longer matches its preflight") from exc
        if (
            prepared.preview.query != INVENTORY_SET_QUANTITIES
            or prepared.preview.skus != canonical_preview.skus
            or prepared.preview.variables != canonical_preview.variables
        ):
            raise IntentConflict("mutation preview was altered after preflight")
        expected_digest = calculate_request_digest(
            batch_id=prepared.batch_id,
            plan_fingerprint=prepared.plan_fingerprint,
            manifest_fingerprint=prepared.manifest_fingerprint,
            preflight_fingerprint=prepared.preflight_fingerprint,
            location_id=prepared.location_id,
            preview=prepared.preview,
        )
        if expected_digest != prepared.request_digest:
            raise IntentConflict("request digest mismatch: prepared payload was altered")

    def reserve(self, prepared: PreparedBatchRequest) -> StoredIntent:
        """Legacy intent-only reservation; does not create an atomic snapshot.

        Future live execution must use SupplierLiveBatchAtomicPreparationRepository
        instead of invoking reserve() and store_snapshot() separately.
        """
        self.validate_prepared(prepared)
        with self._connection_factory() as db:
            db.executescript(SCHEMA_SQL)
            try:
                db.execute("""INSERT INTO supplier_live_batch_intents (
                    operation_id, batch_id, plan_fingerprint, manifest_fingerprint,
                    preflight_fingerprint, location_id, request_digest, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PREPARED')""", (
                    prepared.preview.operation_id, prepared.batch_id,
                    prepared.plan_fingerprint, prepared.manifest_fingerprint,
                    prepared.preflight_fingerprint, prepared.location_id,
                    prepared.request_digest,
                ))
            except sqlite3.IntegrityError as exc:
                row = db.execute("""SELECT operation_id, batch_id, plan_fingerprint,
                    manifest_fingerprint, preflight_fingerprint, location_id, request_digest, status
                    FROM supplier_live_batch_intents
                    WHERE operation_id = ? OR (manifest_fingerprint = ? AND location_id = ?)""", (
                    prepared.preview.operation_id, prepared.manifest_fingerprint, prepared.location_id,
                )).fetchone()
                expected = (
                    prepared.preview.operation_id, prepared.batch_id, prepared.plan_fingerprint,
                    prepared.manifest_fingerprint, prepared.preflight_fingerprint,
                    prepared.location_id, prepared.request_digest, "PREPARED",
                )
                if row is None or tuple(row) != expected:
                    raise IntentConflict("manifest/location or operation ID already reserved for a different request") from exc
            row = db.execute("""SELECT operation_id, batch_id, manifest_fingerprint,
                preflight_fingerprint, request_digest, status
                FROM supplier_live_batch_intents WHERE operation_id = ?""", (
                    prepared.preview.operation_id,
            )).fetchone()
            if row is None:
                raise IntentConflict("intent disappeared after insert")
            return StoredIntent(*tuple(row))
