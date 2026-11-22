from __future__ import annotations

from database.supplier_incident_alert_schema import ensure_supplier_incident_alert_schema


def ensure_supplier_notification_delivery_schema(connection) -> None:
    """Create append-only notification-delivery audit storage."""
    ensure_supplier_incident_alert_schema(connection)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_notification_delivery_events (
            delivery_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            delivery_id TEXT NOT NULL CHECK (LENGTH(delivery_id) = 64),
            route_event_id INTEGER NOT NULL,
            incident_id TEXT NOT NULL CHECK (LENGTH(incident_id) = 64),
            supplier_code TEXT NOT NULL,
            route TEXT NOT NULL CHECK (route IN ('operator_review','immediate_alert','recovery_notice')),
            channel TEXT NOT NULL CHECK (channel IN ('email','slack','webhook')),
            event_type TEXT NOT NULL CHECK (event_type IN ('delivery_started','delivery_delivered','delivery_failed','retry_queued')),
            attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
            idempotency_key TEXT NOT NULL CHECK (LENGTH(idempotency_key) = 64),
            provider_name TEXT NOT NULL,
            provider_message_id TEXT,
            error_message TEXT,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (delivery_id, event_type, attempt_number)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_notification_delivery_success
        ON supplier_notification_delivery_events (delivery_id)
        WHERE event_type = 'delivery_delivered';

        CREATE INDEX IF NOT EXISTS idx_supplier_notification_delivery_supplier
        ON supplier_notification_delivery_events (supplier_code, delivery_event_id);

        CREATE TRIGGER IF NOT EXISTS trg_supplier_notification_delivery_immutable_update
        BEFORE UPDATE ON supplier_notification_delivery_events
        BEGIN
            SELECT RAISE(ABORT, 'supplier_notification_delivery_events is append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_supplier_notification_delivery_immutable_delete
        BEFORE DELETE ON supplier_notification_delivery_events
        BEGIN
            SELECT RAISE(ABORT, 'supplier_notification_delivery_events is append-only');
        END;
        """
    )
