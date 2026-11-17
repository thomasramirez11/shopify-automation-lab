from __future__ import annotations

from database.supplier_execution_schema import (
    ensure_supplier_execution_schema,
)


def ensure_supplier_reconciliation_schema(
    connection,
) -> None:
    """
    Create the append-only execution reconciliation ledger.

    One operation may be reconciled against multiple V1 runs while it is in
    mismatch. Once a MATCH exists, the operation is considered resolved.
    """

    ensure_supplier_execution_schema(
        connection
    )

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_execution_reconciliations (
            reconciliation_id INTEGER PRIMARY KEY AUTOINCREMENT,

            operation_id TEXT NOT NULL,
            verified_event_id INTEGER NOT NULL,
            sync_run_id INTEGER NOT NULL,

            shopify_variant_id TEXT NOT NULL,
            shopify_sku TEXT NOT NULL,

            expected_quantity INTEGER NOT NULL
                CHECK (expected_quantity >= 0),

            observed_sqlite_quantity INTEGER
                CHECK (
                    observed_sqlite_quantity IS NULL
                    OR observed_sqlite_quantity >= 0
                ),

            status TEXT NOT NULL
                CHECK (
                    status IN (
                        'match',
                        'mismatch',
                        'variant_missing'
                    )
                ),

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(
                operation_id,
                sync_run_id
            )
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_reconciliations_operation
        ON supplier_execution_reconciliations (
            operation_id,
            reconciliation_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_reconciliations_status
        ON supplier_execution_reconciliations (
            status,
            reconciliation_id
        );

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_reconciliations_immutable_update
        BEFORE UPDATE ON supplier_execution_reconciliations
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_execution_reconciliations is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_reconciliations_immutable_delete
        BEFORE DELETE ON supplier_execution_reconciliations
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_execution_reconciliations is append-only'
            );
        END;
        """
    )
