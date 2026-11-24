"""V2.8B/3 append-only SQLite recovery journal and immutable request snapshot.

- Depends on an existing V2.8B/2 intent reservation.
- Keeps full *non-secret* GraphQL request bytes for post-crash inspection.
- Never contacts Shopify, submits a mutation or changes the V1 database schema.
- A pre-send DISPATCH_ARMED event records uncertainty conservatively.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Callable, ContextManager

from supplier.batch.live_preflight_bridge import PreparedBatchRequest, calculate_request_digest
from supplier.batch.live_recovery_models import (
    ImmutableRequestSnapshot, RecoveryConflict, RecoveryEvent, RecoveryEventKind,
)
from supplier.batch.live_request_contract import INVENTORY_SET_QUANTITIES, MutationPreview

GENESIS_HASH = "0" * 64
HEX_64 = re.compile(r"^[0-9a-f]{64}$")

RECOVERY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS supplier_live_batch_request_snapshots (
    operation_id TEXT PRIMARY KEY,
    request_digest TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(operation_id) REFERENCES supplier_live_batch_intents(operation_id)
);
CREATE TABLE IF NOT EXISTS supplier_live_batch_dispatch_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN (
        'DISPATCH_ARMED', 'OUTCOME_UNKNOWN', 'READBACK_OBSERVED', 'READBACK_FAILED'
    )),
    details_json TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(operation_id) REFERENCES supplier_live_batch_intents(operation_id),
    UNIQUE(operation_id, sequence)
);
CREATE INDEX IF NOT EXISTS ix_supplier_live_batch_dispatch_events_operation
    ON supplier_live_batch_dispatch_events(operation_id, sequence);
CREATE TRIGGER IF NOT EXISTS trg_supplier_live_batch_snapshots_no_update
BEFORE UPDATE ON supplier_live_batch_request_snapshots BEGIN
    SELECT RAISE(ABORT, 'request snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_supplier_live_batch_snapshots_no_delete
BEFORE DELETE ON supplier_live_batch_request_snapshots BEGIN
    SELECT RAISE(ABORT, 'request snapshots are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_supplier_live_batch_dispatch_no_update
BEFORE UPDATE ON supplier_live_batch_dispatch_events BEGIN
    SELECT RAISE(ABORT, 'dispatch events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_supplier_live_batch_dispatch_no_delete
BEFORE DELETE ON supplier_live_batch_dispatch_events BEGIN
    SELECT RAISE(ABORT, 'dispatch events are append-only');
END;
"""


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event_hash(operation_id: str, sequence: int, kind: str, details_json: str, previous_hash: str) -> str:
    return _hash(_canonical({
        "operation_id": operation_id, "sequence": sequence, "kind": kind,
        "details": json.loads(details_json), "previous_hash": previous_hash,
    }))


class SupplierLiveBatchRecoveryRepository:
    """Persistence only. The service owns transition policy and readback."""

    def __init__(self, *, connection_factory: Callable[[], ContextManager[sqlite3.Connection]]) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _initialize(db: sqlite3.Connection) -> None:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(RECOVERY_SCHEMA_SQL)

    @staticmethod
    def _get_intent(db: sqlite3.Connection, operation_id: str) -> tuple:
        try:
            row = db.execute("""SELECT operation_id, batch_id, plan_fingerprint,
                manifest_fingerprint, preflight_fingerprint, location_id,
                request_digest, status FROM supplier_live_batch_intents
                WHERE operation_id = ?""", (operation_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            raise RecoveryConflict("V2.8B/2 intent ledger is missing; reserve an intent first") from exc
        if row is None or row[7] != "PREPARED":
            raise RecoveryConflict("no matching PREPARED intent exists")
        return tuple(row)

    @staticmethod
    def _make_payload(prepared: PreparedBatchRequest) -> dict:
        preview = prepared.preview
        return {
            "operation_id": preview.operation_id,
            "batch_id": prepared.batch_id,
            "plan_fingerprint": prepared.plan_fingerprint,
            "manifest_fingerprint": prepared.manifest_fingerprint,
            "preflight_fingerprint": prepared.preflight_fingerprint,
            "location_id": prepared.location_id,
            "request_digest": prepared.request_digest,
            "query": preview.query,
            "variables": preview.variables,
            "skus": list(preview.skus),
        }

    @staticmethod
    def _validate_payload(payload: dict, intent: tuple) -> str:
        (operation_id, batch_id, plan_fingerprint, manifest_fingerprint,
         preflight_fingerprint, location_id, request_digest, _status) = intent
        expected = (operation_id, batch_id, plan_fingerprint, manifest_fingerprint,
                    preflight_fingerprint, location_id, request_digest)
        got = tuple(payload.get(field) for field in (
            "operation_id", "batch_id", "plan_fingerprint", "manifest_fingerprint",
            "preflight_fingerprint", "location_id", "request_digest",
        ))
        if got != expected or payload.get("query") != INVENTORY_SET_QUANTITIES:
            raise RecoveryConflict("snapshot identity or GraphQL contract differs from reserved intent")
        variables = payload.get("variables")
        skus = payload.get("skus")
        if not isinstance(variables, dict) or not isinstance(skus, list) or len(skus) != 2:
            raise RecoveryConflict("snapshot variables or two-item SKU list is malformed")
        quantities = variables.get("input", {}).get("quantities") if isinstance(variables.get("input"), dict) else None
        if (
            not isinstance(quantities, list) or len(quantities) != 2
            or variables.get("idempotencyKey") != operation_id
            or variables["input"].get("referenceDocumentUri")
                != f"shopify-automation-lab://v2/operations/{operation_id}"
        ):
            raise RecoveryConflict("snapshot quantities or idempotency key differ from reserved intent")
        for quantity in quantities:
            if not isinstance(quantity, dict) or set(quantity) != {
                "inventoryItemId", "locationId", "quantity", "changeFromQuantity"
            }:
                raise RecoveryConflict("snapshot CAS quantities malformed")
            if quantity["locationId"] != location_id or not isinstance(quantity["inventoryItemId"], str):
                raise RecoveryConflict("snapshot target differs from approved location")
            for name in ("quantity", "changeFromQuantity"):
                if type(quantity[name]) is not int or quantity[name] < 0:
                    raise RecoveryConflict("snapshot quantity must be a nonnegative int")
        preview = MutationPreview(
            operation_id=operation_id, skus=tuple(skus),
            query=payload["query"], variables=variables,
        )
        computed = calculate_request_digest(
            batch_id=batch_id, plan_fingerprint=plan_fingerprint,
            manifest_fingerprint=manifest_fingerprint,
            preflight_fingerprint=preflight_fingerprint, location_id=location_id,
            preview=preview,
        )
        if not isinstance(request_digest, str) or not HEX_64.fullmatch(request_digest) or computed != request_digest:
            raise RecoveryConflict("snapshot digest mismatch")
        return computed

    def store_snapshot(self, prepared: PreparedBatchRequest) -> ImmutableRequestSnapshot:
        """Store a full immutable request AFTER V2.8B/2 reserve(prepared).

        Safe if repeated with an identical payload; conflicting payloads fail closed.
        """
        if not isinstance(prepared, PreparedBatchRequest) or prepared.mode != "OFFLINE_PREVIEW_ONLY":
            raise RecoveryConflict("only a previously validated offline prepared request is accepted")
        payload = self._make_payload(prepared)
        encoded = _canonical(payload)
        payload_sha = _hash(encoded)
        operation_id = prepared.preview.operation_id
        with self._connection_factory() as db:
            self._initialize(db)
            db.execute("BEGIN IMMEDIATE")
            intent = self._get_intent(db, operation_id)
            self._validate_payload(payload, intent)
            row = db.execute("""SELECT request_digest, payload_json, payload_sha256
                FROM supplier_live_batch_request_snapshots WHERE operation_id=?""", (operation_id,)).fetchone()
            if row is None:
                db.execute("""INSERT INTO supplier_live_batch_request_snapshots
                    (operation_id, request_digest, payload_json, payload_sha256)
                    VALUES (?, ?, ?, ?)""", (operation_id, prepared.request_digest, encoded, payload_sha))
            elif tuple(row) != (prepared.request_digest, encoded, payload_sha):
                raise RecoveryConflict("immutable request snapshot already exists with different contents")
        return ImmutableRequestSnapshot(operation_id, prepared.request_digest, payload_sha, json.loads(encoded))

    def load_snapshot(self, operation_id: str) -> ImmutableRequestSnapshot:
        with self._connection_factory() as db:
            self._initialize(db)
            intent = self._get_intent(db, operation_id)
            row = db.execute("""SELECT request_digest, payload_json, payload_sha256
                FROM supplier_live_batch_request_snapshots WHERE operation_id=?""", (operation_id,)).fetchone()
            if row is None:
                raise RecoveryConflict("immutable request snapshot is missing")
            digest, encoded, sha = tuple(row)
            if _hash(encoded) != sha:
                raise RecoveryConflict("request snapshot SHA-256 checksum mismatch")
            try:
                parsed = json.loads(encoded)
            except (ValueError, TypeError) as exc:
                raise RecoveryConflict("corrupt request snapshot") from exc
            if not isinstance(parsed, dict) or _canonical(parsed) != encoded or digest != intent[6]:
                raise RecoveryConflict("noncanonical or wrong-digest snapshot")
            self._validate_payload(parsed, intent)
            return ImmutableRequestSnapshot(operation_id, digest, sha, parsed)

    @staticmethod
    def _read_events(db: sqlite3.Connection, operation_id: str) -> tuple[RecoveryEvent, ...]:
        rows = db.execute("""SELECT sequence, kind, details_json, previous_hash, event_hash
            FROM supplier_live_batch_dispatch_events WHERE operation_id=? ORDER BY sequence""", (operation_id,)).fetchall()
        previous = GENESIS_HASH
        result = []
        for expected_sequence, row in enumerate(rows, 1):
            sequence, kind, details_json, prior, digest = row
            try:
                event_kind = RecoveryEventKind(kind)
                details = json.loads(details_json)
                canonical = _canonical(details)
                expected_hash = _event_hash(operation_id, sequence, kind, details_json, prior)
            except (TypeError, ValueError) as exc:
                raise RecoveryConflict("invalid event record encountered") from exc
            if (
                sequence != expected_sequence or prior != previous or digest != expected_hash
                or canonical != details_json or not isinstance(details, dict)
            ):
                raise RecoveryConflict("append-only dispatch hash chain failed integrity check")
            result.append(RecoveryEvent(operation_id, sequence, event_kind, details, prior, digest))
            previous = digest
        return tuple(result)

    def events(self, operation_id: str) -> tuple[RecoveryEvent, ...]:
        self.load_snapshot(operation_id)  # Verify the base identity even for read-only history.
        with self._connection_factory() as db:
            self._initialize(db)
            return self._read_events(db, operation_id)

    def append_event(
        self, operation_id: str, *, kind: RecoveryEventKind,
        details: dict, expected_event_count: int,
    ) -> RecoveryEvent:
        """Atomic optimistic transition. Never dispatch from this method."""
        if not isinstance(kind, RecoveryEventKind) or not isinstance(details, dict):
            raise RecoveryConflict("invalid event type or details")
        if type(expected_event_count) is not int or expected_event_count < 0:
            raise RecoveryConflict("expected_event_count must be nonnegative integer")
        # No unstructured exception details or credentials allowed in the journal.
        if any(not isinstance(key, str) for key in details):
            raise RecoveryConflict("event detail names must be strings")
        details_json = _canonical(details)
        if len(details_json) > 4096:
            raise RecoveryConflict("event details too large")
        self.load_snapshot(operation_id)
        with self._connection_factory() as db:
            self._initialize(db)
            db.execute("BEGIN IMMEDIATE")
            self._get_intent(db, operation_id)
            rows = self._read_events(db, operation_id)
            if len(rows) != expected_event_count:
                raise RecoveryConflict("dispatch journal changed; concurrent or repeated transition blocked")
            # Enforce the transition sequence at the persistence boundary as well
            # as in the service, so future callers cannot accidentally bypass it.
            if not rows:
                allowed = kind == RecoveryEventKind.DISPATCH_ARMED and details == {
                    "request_digest": self._get_intent(db, operation_id)[6]
                }
            elif kind == RecoveryEventKind.OUTCOME_UNKNOWN:
                allowed = rows[-1].kind == RecoveryEventKind.DISPATCH_ARMED and details == {
                    "reason": "transport_result_unavailable"
                }
            elif kind == RecoveryEventKind.READBACK_FAILED:
                allowed = details == {"reason": "readback_unavailable_or_untrusted"}
            elif kind == RecoveryEventKind.READBACK_OBSERVED:
                observations = details.get("observations")
                allowed = (
                    set(details) == {"observations"} and isinstance(observations, list)
                    and len(observations) == 2
                    and all(isinstance(x, dict) and set(x) == {
                        "sku", "inventory_item_id", "before", "after", "observed", "classification"
                    } for x in observations)
                    and all(x["classification"] in ("TARGET", "BASELINE", "DIVERGED") for x in observations)
                )
            else:
                allowed = False
            if not allowed:
                raise RecoveryConflict("unsafe or malformed recovery state transition blocked")
            previous = rows[-1].event_hash if rows else GENESIS_HASH
            sequence = len(rows) + 1
            digest = _event_hash(operation_id, sequence, kind.value, details_json, previous)
            db.execute("""INSERT INTO supplier_live_batch_dispatch_events
                (operation_id, sequence, kind, details_json, previous_hash, event_hash)
                VALUES (?, ?, ?, ?, ?, ?)""", (
                    operation_id, sequence, kind.value, details_json, previous, digest,
            ))
            return RecoveryEvent(operation_id, sequence, kind, json.loads(details_json), previous, digest)
