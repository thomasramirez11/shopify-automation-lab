from __future__ import annotations

from database.supplier_incident_schema import (
    ensure_supplier_incident_schema,
)


def ensure_supplier_incident_alert_schema(
    connection,
) -> None:
    """
    Create the append-only incident alert-routing ledger.

    This table records routing decisions only. It does not prove that an
    external notification was actually delivered.
    """

    ensure_supplier_incident_schema(
        connection
    )

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_incident_alert_routes (
            route_event_id INTEGER PRIMARY KEY AUTOINCREMENT,

            incident_id TEXT NOT NULL
                CHECK (LENGTH(incident_id) = 64),

            source_incident_event_id INTEGER NOT NULL,

            supplier_code TEXT NOT NULL,

            source_event_type TEXT NOT NULL
                CHECK (
                    source_event_type IN (
                        'incident_opened',
                        'incident_escalated',
                        'incident_deescalated',
                        'incident_closed'
                    )
                ),

            severity TEXT NOT NULL
                CHECK (
                    severity IN (
                        'info',
                        'warning',
                        'critical'
                    )
                ),

            route TEXT NOT NULL
                CHECK (
                    route IN (
                        'dashboard',
                        'operator_review',
                        'immediate_alert',
                        'recovery_notice'
                    )
                ),

            policy_fingerprint TEXT NOT NULL
                CHECK (LENGTH(policy_fingerprint) = 64),

            route_fingerprint TEXT NOT NULL
                CHECK (LENGTH(route_fingerprint) = 64),

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (
                incident_id,
                source_incident_event_id,
                route
            ),

            UNIQUE (
                route_fingerprint
            )
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_incident_alert_routes_incident
        ON supplier_incident_alert_routes (
            incident_id,
            route_event_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_incident_alert_routes_supplier
        ON supplier_incident_alert_routes (
            supplier_code,
            route_event_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_incident_alert_routes_severity
        ON supplier_incident_alert_routes (
            severity,
            route_event_id
        );

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_incident_alert_routes_immutable_update
        BEFORE UPDATE ON supplier_incident_alert_routes
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_incident_alert_routes is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_incident_alert_routes_immutable_delete
        BEFORE DELETE ON supplier_incident_alert_routes
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_incident_alert_routes is append-only'
            );
        END;
        """
    )
