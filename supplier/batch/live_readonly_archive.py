"""V2.8B/6: inspect a persisted recovery archive WITHOUT writing to SQLite.

No schema creation or migration. SQLite `mode=ro` + `query_only=ON` ensures
that accidental INSERT/UPDATE statements cannot change the archive file.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

from supplier.batch.live_recovery_models import ImmutableRequestSnapshot, RecoveryConflict
from supplier.batch.live_recovery_repository import (
    SupplierLiveBatchRecoveryRepository, _canonical, _hash,
)


class ReadOnlyRecoveryArchive:
    def __init__(self, database_file: Path | str):
        path = Path(database_file).resolve(strict=True)
        if not path.is_file():
            raise RecoveryConflict("recovery archive path must point to a file")
        self._path = path

    def load_verified(self, operation_id: str):
        """Return a verified snapshot and journal under one read transaction."""
        try:
            uid = UUID(operation_id)
            if uid.version != 4 or str(uid) != operation_id:
                raise ValueError("not a canonical UUIDv4")
        except (TypeError, ValueError, AttributeError) as exc:
            raise RecoveryConflict("operation_id must be canonical UUIDv4") from exc
        uri = self._path.as_uri() + "?mode=ro"
        # The read transaction keeps the snapshot and journal consistent even
        # if a separate process appends audit events during inspection.
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=5.0)) as db:
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
                intent = SupplierLiveBatchRecoveryRepository._get_intent(db, operation_id)
                row = db.execute("""SELECT request_digest, payload_json, payload_sha256
                    FROM supplier_live_batch_request_snapshots WHERE operation_id=?""", (operation_id,)).fetchone()
                if row is None:
                    raise RecoveryConflict("immutable request snapshot is missing")
                request_digest, encoded, checksum = row
                if type(encoded) is not str or type(checksum) is not str or _hash(encoded) != checksum:
                    raise RecoveryConflict("immutable request checksum mismatch")
                payload = json.loads(encoded)
                if not isinstance(payload, dict) or _canonical(payload) != encoded or request_digest != intent[6]:
                    raise RecoveryConflict("immutable request payload mismatch")
                SupplierLiveBatchRecoveryRepository._validate_payload(payload, intent)
                events = SupplierLiveBatchRecoveryRepository._read_events(db, operation_id)
                return ImmutableRequestSnapshot(operation_id, request_digest, checksum, payload), events
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise RecoveryConflict("read-only archive unavailable or corrupted") from exc
