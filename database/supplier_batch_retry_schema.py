from __future__ import annotations

from database.supplier_batch_execution_schema import (
    ensure_supplier_batch_execution_schema,
)


def ensure_supplier_batch_retry_schema(
    connection,
) -> None:
    """
    Create the append-only retry/recovery ledger.

    Retries never rewrite the original failed batch item event. Recovery is
    recorded as a separate timeline linked back to the original operation.
    """

    ensure_supplier_batch_execution_schema(
        connection
    )

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_batch_retry_events (
            retry_event_id INTEGER PRIMARY KEY AUTOINCREMENT,

            retry_id TEXT NOT NULL,
            source_batch_id TEXT NOT NULL,
            item_index INTEGER NOT NULL
                CHECK (item_index >= 1),
            operation_id TEXT NOT NULL,

            shopify_variant_id TEXT NOT NULL,
            shopify_sku TEXT NOT NULL,

            before_quantity INTEGER NOT NULL
                CHECK (before_quantity >= 0),
            requested_quantity INTEGER NOT NULL
                CHECK (requested_quantity >= 0),
            inventory_delta INTEGER NOT NULL,

            attempt_number INTEGER NOT NULL
                CHECK (attempt_number >= 1),

            event_type TEXT NOT NULL
                CHECK (
                    event_type IN (
                        'retry_queued',
                        'retry_started',
                        'retry_succeeded',
                        'retry_failed',
                        'retry_exhausted',
                        'retry_skipped'
                    )
                ),

            error_message TEXT,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(
                retry_id,
                attempt_number,
                event_type
            )
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_batch_retry_retry
        ON supplier_batch_retry_events (
            retry_id,
            retry_event_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_batch_retry_source
        ON supplier_batch_retry_events (
            source_batch_id,
            item_index,
            retry_event_id
        );

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_batch_retry_attempt_outcome
        ON supplier_batch_retry_events (
            retry_id,
            attempt_number
        )
        WHERE event_type IN (
            'retry_succeeded',
            'retry_failed'
        );

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_batch_retry_success
        ON supplier_batch_retry_events (
            retry_id
        )
        WHERE event_type = 'retry_succeeded';

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_batch_retry_exhausted
        ON supplier_batch_retry_events (
            retry_id
        )
        WHERE event_type = 'retry_exhausted';

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_batch_retry_immutable_update
        BEFORE UPDATE ON supplier_batch_retry_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_batch_retry_events is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_batch_retry_immutable_delete
        BEFORE DELETE ON supplier_batch_retry_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_batch_retry_events is append-only'
            );
        END;
        """
    )
