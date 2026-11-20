from __future__ import annotations


def ensure_supplier_orchestration_schema(connection) -> None:
    """Create / migrate the append-only control-plane run ledger."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_orchestration_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_code TEXT NOT NULL,
            orchestration_fingerprint TEXT NOT NULL CHECK (LENGTH(orchestration_fingerprint) = 64),
            manifest_fingerprint TEXT NOT NULL CHECK (LENGTH(manifest_fingerprint) = 64),
            policy_fingerprint TEXT NOT NULL DEFAULT '',
            posture TEXT NOT NULL,
            next_action TEXT NOT NULL,
            planned_mutations INTEGER NOT NULL CHECK (planned_mutations >= 0),
            review_items INTEGER NOT NULL CHECK (review_items >= 0),
            blocked_items INTEGER NOT NULL CHECK (blocked_items >= 0),
            no_action_items INTEGER NOT NULL CHECK (no_action_items >= 0),
            queued_retry_attempts INTEGER NOT NULL CHECK (queued_retry_attempts >= 0),
            dead_letter_awaiting_human INTEGER NOT NULL CHECK (dead_letter_awaiting_human >= 0),
            dead_letter_acknowledged INTEGER NOT NULL CHECK (dead_letter_acknowledged >= 0),
            resolution_recorded INTEGER NOT NULL CHECK (resolution_recorded >= 0),
            reentry_authorized INTEGER NOT NULL CHECK (reentry_authorized >= 0),
            reentry_started INTEGER NOT NULL CHECK (reentry_started >= 0),
            reentry_failed INTEGER NOT NULL CHECK (reentry_failed >= 0),
            resolution_closed INTEGER NOT NULL CHECK (resolution_closed >= 0),
            previous_run_id INTEGER,
            previous_posture TEXT,
            previous_policy_fingerprint TEXT,
            posture_changed INTEGER NOT NULL CHECK (posture_changed IN (0,1)),
            next_action_changed INTEGER NOT NULL CHECK (next_action_changed IN (0,1)),
            policy_changed INTEGER NOT NULL DEFAULT 0 CHECK (policy_changed IN (0,1)),
            manifest_changed INTEGER NOT NULL DEFAULT 0 CHECK (manifest_changed IN (0,1)),
            snapshot_changed INTEGER NOT NULL DEFAULT 0 CHECK (snapshot_changed IN (0,1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_supplier_orchestration_runs_supplier
        ON supplier_orchestration_runs (supplier_code, run_id);

        CREATE INDEX IF NOT EXISTS idx_supplier_orchestration_runs_posture
        ON supplier_orchestration_runs (posture, run_id);

        CREATE TRIGGER IF NOT EXISTS trg_supplier_orchestration_runs_immutable_update
        BEFORE UPDATE ON supplier_orchestration_runs
        BEGIN
            SELECT RAISE(ABORT, 'supplier_orchestration_runs is append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_supplier_orchestration_runs_immutable_delete
        BEFORE DELETE ON supplier_orchestration_runs
        BEGIN
            SELECT RAISE(ABORT, 'supplier_orchestration_runs is append-only');
        END;
        """
    )
    _migrate_v27e_columns(connection)


def _migrate_v27e_columns(connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(supplier_orchestration_runs);"
        ).fetchall()
    }
    additions = {
        "policy_fingerprint": "TEXT NOT NULL DEFAULT ''",
        "previous_policy_fingerprint": "TEXT",
        "policy_changed": "INTEGER NOT NULL DEFAULT 0",
        "manifest_changed": "INTEGER NOT NULL DEFAULT 0",
        "snapshot_changed": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE supplier_orchestration_runs ADD COLUMN {name} {definition};"
            )
