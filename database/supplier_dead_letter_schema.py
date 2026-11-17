from __future__ import annotations

from database.supplier_batch_retry_schema import (
    ensure_supplier_batch_retry_schema,
)


def ensure_supplier_dead_letter_schema(
    connection,
) -> None:
    """
    Create the append-only dead-letter / human-escalation ledger.

    A dead-letter case is created only after automation explicitly gives up
    ownership because the retry budget was exhausted or the failure was
    classified as non-retryable.
    """

    ensure_supplier_batch_retry_schema(
        connection
    )

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_dead_letter_events (
            dead_letter_event_id INTEGER PRIMARY KEY AUTOINCREMENT,

            case_id TEXT NOT NULL
                CHECK (LENGTH(case_id) = 64),

            source_retry_id TEXT NOT NULL
                CHECK (LENGTH(source_retry_id) = 64),

            source_batch_id TEXT NOT NULL
                CHECK (LENGTH(source_batch_id) = 64),

            item_index INTEGER NOT NULL
                CHECK (item_index >= 1),

            operation_id TEXT NOT NULL
                CHECK (LENGTH(operation_id) = 64),

            shopify_variant_id TEXT NOT NULL,
            shopify_sku TEXT NOT NULL,

            requested_quantity INTEGER NOT NULL
                CHECK (requested_quantity >= 0),

            reason_code TEXT NOT NULL
                CHECK (
                    reason_code IN (
                        'retry_exhausted',
                        'non_retryable_failure'
                    )
                ),

            event_type TEXT NOT NULL
                CHECK (
                    event_type IN (
                        'case_opened',
                        'case_acknowledged'
                    )
                ),

            actor TEXT,
            note TEXT,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(
                case_id,
                event_type
            )
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_dead_letter_case
        ON supplier_dead_letter_events (
            case_id,
            dead_letter_event_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_dead_letter_reason
        ON supplier_dead_letter_events (
            reason_code,
            dead_letter_event_id
        );

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_dead_letter_source_retry
        ON supplier_dead_letter_events (
            source_retry_id
        )
        WHERE event_type = 'case_opened';

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_dead_letter_immutable_update
        BEFORE UPDATE ON supplier_dead_letter_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_dead_letter_events is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_dead_letter_immutable_delete
        BEFORE DELETE ON supplier_dead_letter_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_dead_letter_events is append-only'
            );
        END;
        """
    )
