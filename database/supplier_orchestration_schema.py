from __future__ import annotations


def ensure_supplier_orchestration_schema(connection) -> None:
    """Create the append-only control-plane run ledger."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_orchestration_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_code TEXT NOT NULL,
            orchestration_fingerprint TEXT NOT NULL CHECK (LENGTH(orchestration_fingerprint) = 64),
            manifest_fingerprint TEXT NOT NULL CHECK (LENGTH(manifest_fingerprint) = 64),
            posture TEXT NOT NULL CHECK (posture IN (
                'idle','ready_for_approval','review_required','blocked','recovery_pending','human_attention'
            )),
            next_action TEXT NOT NULL CHECK (next_action IN (
                'none','approve_batch','review_batch','fix_blocking_issues','process_retry_queue','review_dead_letter_cases'
            )),
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
            posture_changed INTEGER NOT NULL CHECK (posture_changed IN (0,1)),
            next_action_changed INTEGER NOT NULL CHECK (next_action_changed IN (0,1)),
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
