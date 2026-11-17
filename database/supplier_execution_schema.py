from __future__ import annotations


def ensure_supplier_execution_schema(connection) -> None:
    """
    Create and harden the append-only V2 supplier execution event ledger.

    baseline_sync_run_id records the newest successful V1 sync that already
    existed when the V2 operation began. Reconciliation must later use a
    successful V1 run with a larger ID.

    Safe to call repeatedly.
    """

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_execution_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL,
            event_type TEXT NOT NULL
                CHECK (
                    event_type IN (
                        'execution_started',
                        'execution_verified',
                        'execution_failed'
                    )
                ),

            supplier_code TEXT NOT NULL,
            supplier_sku TEXT NOT NULL,

            shopify_variant_id TEXT NOT NULL,
            shopify_sku TEXT NOT NULL,
            inventory_item_id TEXT NOT NULL,
            location_id TEXT NOT NULL,

            before_quantity INTEGER NOT NULL
                CHECK (before_quantity >= 0),
            requested_quantity INTEGER NOT NULL
                CHECK (requested_quantity >= 0),
            observed_after_quantity INTEGER
                CHECK (
                    observed_after_quantity IS NULL
                    OR observed_after_quantity >= 0
                ),
            inventory_delta INTEGER NOT NULL,

            plan_fingerprint TEXT NOT NULL
                CHECK (LENGTH(plan_fingerprint) = 64),
            idempotency_key TEXT NOT NULL,

            baseline_sync_run_id INTEGER NOT NULL
                DEFAULT 0
                CHECK (baseline_sync_run_id >= 0),

            error_message TEXT,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(operation_id, event_type)
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_execution_events_operation
        ON supplier_execution_events (
            operation_id,
            event_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_execution_events_variant
        ON supplier_execution_events (
            shopify_variant_id,
            event_id
        );

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_execution_events_immutable_update
        BEFORE UPDATE ON supplier_execution_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_execution_events is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_execution_events_immutable_delete
        BEFORE DELETE ON supplier_execution_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_execution_events is append-only'
            );
        END;
        """
    )

    # Migration path from V2.5E.1. The user's ledger is currently empty, but
    # this also behaves safely if a future environment upgrades later.
    columns = {
        row["name"]
        for row in connection.execute(
            """
            PRAGMA table_info(
                supplier_execution_events
            );
            """
        ).fetchall()
    }

    if "baseline_sync_run_id" not in columns:
        connection.execute(
            """
            ALTER TABLE supplier_execution_events
            ADD COLUMN baseline_sync_run_id INTEGER NOT NULL
                DEFAULT 0
                CHECK (baseline_sync_run_id >= 0);
            """
        )
