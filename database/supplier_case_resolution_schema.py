from __future__ import annotations

from database.supplier_dead_letter_schema import (
    ensure_supplier_dead_letter_schema,
)


def ensure_supplier_case_resolution_schema(
    connection,
) -> None:
    """
    Create the append-only case-resolution and controlled re-entry ledger.

    The original dead-letter history remains untouched. Resolution is a new
    timeline layered on top of the acknowledged human case.
    """

    ensure_supplier_dead_letter_schema(
        connection
    )

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_case_resolution_events (
            resolution_event_id INTEGER PRIMARY KEY AUTOINCREMENT,

            case_id TEXT NOT NULL
                CHECK (LENGTH(case_id) = 64),

            resolution_fingerprint TEXT NOT NULL
                CHECK (LENGTH(resolution_fingerprint) = 64),

            event_type TEXT NOT NULL
                CHECK (
                    event_type IN (
                        'resolution_recorded',
                        'reentry_authorized',
                        'reentry_started',
                        'reentry_succeeded',
                        'reentry_failed',
                        'case_closed'
                    )
                ),

            resolution_code TEXT NOT NULL
                CHECK (
                    resolution_code IN (
                        'supplier_fixed',
                        'credentials_fixed',
                        'configuration_fixed',
                        'manual_data_correction',
                        'other'
                    )
                ),

            actor TEXT NOT NULL,
            note TEXT NOT NULL,

            shopify_variant_id TEXT NOT NULL,
            shopify_sku TEXT NOT NULL,

            requested_quantity INTEGER NOT NULL
                CHECK (requested_quantity >= 0),

            error_message TEXT,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (
                case_id,
                event_type
            )
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_case_resolution_case
        ON supplier_case_resolution_events (
            case_id,
            resolution_event_id
        );

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_case_resolution_single_reentry_outcome
        ON supplier_case_resolution_events (
            case_id
        )
        WHERE event_type IN (
            'reentry_succeeded',
            'reentry_failed'
        );

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_case_resolution_immutable_update
        BEFORE UPDATE ON supplier_case_resolution_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_case_resolution_events is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_case_resolution_immutable_delete
        BEFORE DELETE ON supplier_case_resolution_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_case_resolution_events is append-only'
            );
        END;
        """
    )
