from __future__ import annotations


def ensure_supplier_incident_schema(
    connection,
) -> None:
    """
    Create append-only health-observation and incident-event ledgers.

    Health observations answer:
        "What did the control plane observe?"

    Incident events answer:
        "What operational incident was opened, changed severity, or recovered?"
    """

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_health_events (
            health_event_id INTEGER PRIMARY KEY AUTOINCREMENT,

            supplier_code TEXT NOT NULL,

            health_fingerprint TEXT NOT NULL
                CHECK (LENGTH(health_fingerprint) = 64),

            health_status TEXT NOT NULL
                CHECK (
                    health_status IN (
                        'healthy',
                        'degraded',
                        'critical'
                    )
                ),

            health_score INTEGER NOT NULL
                CHECK (
                    health_score >= 0
                    AND health_score <= 100
                ),

            slo_compliance_percentage REAL NOT NULL
                CHECK (
                    slo_compliance_percentage >= 0
                    AND slo_compliance_percentage <= 100
                ),

            slos_met INTEGER NOT NULL
                CHECK (slos_met >= 0),

            slo_count INTEGER NOT NULL
                CHECK (slo_count >= 0),

            history_runs_evaluated INTEGER NOT NULL
                CHECK (history_runs_evaluated >= 0),

            healthy_run_percentage REAL NOT NULL
                CHECK (
                    healthy_run_percentage >= 0
                    AND healthy_run_percentage <= 100
                ),

            consecutive_healthy_runs INTEGER NOT NULL
                CHECK (consecutive_healthy_runs >= 0),

            unresolved_human_cases INTEGER NOT NULL
                CHECK (unresolved_human_cases >= 0),

            queued_retry_attempts INTEGER NOT NULL
                CHECK (queued_retry_attempts >= 0),

            reasons_json TEXT NOT NULL,

            slo_policy_fingerprint TEXT NOT NULL
                CHECK (LENGTH(slo_policy_fingerprint) = 64),

            previous_health_event_id INTEGER,
            previous_health_status TEXT,

            status_changed INTEGER NOT NULL
                CHECK (status_changed IN (0, 1)),

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_health_events_supplier
        ON supplier_health_events (
            supplier_code,
            health_event_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_health_events_status
        ON supplier_health_events (
            health_status,
            health_event_id
        );

        CREATE TABLE IF NOT EXISTS supplier_incident_events (
            incident_event_id INTEGER PRIMARY KEY AUTOINCREMENT,

            incident_id TEXT NOT NULL
                CHECK (LENGTH(incident_id) = 64),

            supplier_code TEXT NOT NULL,

            source_health_event_id INTEGER NOT NULL,

            event_type TEXT NOT NULL
                CHECK (
                    event_type IN (
                        'incident_opened',
                        'incident_escalated',
                        'incident_deescalated',
                        'incident_closed'
                    )
                ),

            health_status TEXT NOT NULL
                CHECK (
                    health_status IN (
                        'healthy',
                        'degraded',
                        'critical'
                    )
                ),

            health_score INTEGER NOT NULL
                CHECK (
                    health_score >= 0
                    AND health_score <= 100
                ),

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (
                incident_id,
                source_health_event_id,
                event_type
            )
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_incident_events_incident
        ON supplier_incident_events (
            incident_id,
            incident_event_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_incident_events_supplier
        ON supplier_incident_events (
            supplier_code,
            incident_event_id
        );

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_incident_single_open
        ON supplier_incident_events (
            incident_id
        )
        WHERE event_type = 'incident_opened';

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_incident_single_close
        ON supplier_incident_events (
            incident_id
        )
        WHERE event_type = 'incident_closed';

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_health_events_immutable_update
        BEFORE UPDATE ON supplier_health_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_health_events is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_health_events_immutable_delete
        BEFORE DELETE ON supplier_health_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_health_events is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_incident_events_immutable_update
        BEFORE UPDATE ON supplier_incident_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_incident_events is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_incident_events_immutable_delete
        BEFORE DELETE ON supplier_incident_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_incident_events is append-only'
            );
        END;
        """
    )
