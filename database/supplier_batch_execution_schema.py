from __future__ import annotations


def ensure_supplier_batch_execution_schema(
    connection,
) -> None:
    """
    Create the append-only parent/child batch execution audit ledger.

    Parent table:
        supplier_batch_execution_events

    Child table:
        supplier_batch_item_events

    Both ledgers are immutable after INSERT.
    """

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_batch_execution_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,

            batch_id TEXT NOT NULL,
            event_type TEXT NOT NULL
                CHECK (
                    event_type IN (
                        'batch_started',
                        'batch_completed',
                        'batch_partial_failure',
                        'batch_failed'
                    )
                ),

            source_plan_fingerprint TEXT NOT NULL
                CHECK (LENGTH(source_plan_fingerprint) = 64),

            manifest_fingerprint TEXT NOT NULL
                CHECK (LENGTH(manifest_fingerprint) = 64),

            planned_mutations INTEGER NOT NULL
                CHECK (planned_mutations >= 0),

            total_absolute_inventory_delta INTEGER NOT NULL
                CHECK (total_absolute_inventory_delta >= 0),

            attempted_mutations INTEGER NOT NULL
                CHECK (attempted_mutations >= 0),

            applied_mutations INTEGER NOT NULL
                CHECK (applied_mutations >= 0),

            failed_mutations INTEGER NOT NULL
                CHECK (failed_mutations >= 0),

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(
                batch_id,
                event_type
            )
        );

        CREATE TABLE IF NOT EXISTS supplier_batch_item_events (
            item_event_id INTEGER PRIMARY KEY AUTOINCREMENT,

            batch_id TEXT NOT NULL,
            item_index INTEGER NOT NULL
                CHECK (item_index >= 1),

            operation_id TEXT NOT NULL,

            event_type TEXT NOT NULL
                CHECK (
                    event_type IN (
                        'item_started',
                        'item_applied',
                        'item_failed'
                    )
                ),

            supplier_sku TEXT NOT NULL,
            shopify_variant_id TEXT NOT NULL,
            shopify_sku TEXT NOT NULL,

            before_quantity INTEGER NOT NULL
                CHECK (before_quantity >= 0),

            requested_quantity INTEGER NOT NULL
                CHECK (requested_quantity >= 0),

            inventory_delta INTEGER NOT NULL,

            error_message TEXT,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(
                batch_id,
                item_index,
                event_type
            )
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_batch_execution_batch
        ON supplier_batch_execution_events (
            batch_id,
            event_id
        );

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_batch_single_terminal
        ON supplier_batch_execution_events (
            batch_id
        )
        WHERE event_type IN (
            'batch_completed',
            'batch_partial_failure',
            'batch_failed'
        );

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_batch_item_single_outcome
        ON supplier_batch_item_events (
            batch_id,
            item_index
        )
        WHERE event_type IN (
            'item_applied',
            'item_failed'
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_batch_items_batch
        ON supplier_batch_item_events (
            batch_id,
            item_index,
            item_event_id
        );

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_batch_execution_immutable_update
        BEFORE UPDATE ON supplier_batch_execution_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_batch_execution_events is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_batch_execution_immutable_delete
        BEFORE DELETE ON supplier_batch_execution_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_batch_execution_events is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_batch_items_immutable_update
        BEFORE UPDATE ON supplier_batch_item_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_batch_item_events is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_batch_items_immutable_delete
        BEFORE DELETE ON supplier_batch_item_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_batch_item_events is append-only'
            );
        END;
        """
    )
