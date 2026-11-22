from __future__ import annotations

from database.supplier_notification_delivery_schema import (
    ensure_supplier_notification_delivery_schema,
)


def ensure_supplier_notification_outbox_schema(
    connection,
) -> None:
    """
    Create the append-only durable notification outbox.

    The outbox makes notification intent durable before provider delivery.
    A worker can safely resume an interrupted CLAIMED job because the
    NotificationMessage idempotency key is deterministic.
    """

    ensure_supplier_notification_delivery_schema(
        connection
    )

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_notification_outbox_events (
            outbox_event_id INTEGER PRIMARY KEY AUTOINCREMENT,

            delivery_id TEXT NOT NULL
                CHECK (LENGTH(delivery_id) = 64),

            route_event_id INTEGER NOT NULL,

            incident_id TEXT NOT NULL
                CHECK (LENGTH(incident_id) = 64),

            supplier_code TEXT NOT NULL,

            route TEXT NOT NULL
                CHECK (
                    route IN (
                        'operator_review',
                        'immediate_alert',
                        'recovery_notice'
                    )
                ),

            channel TEXT NOT NULL
                CHECK (
                    channel IN (
                        'email',
                        'slack',
                        'webhook'
                    )
                ),

            event_type TEXT NOT NULL
                CHECK (
                    event_type IN (
                        'outbox_enqueued',
                        'outbox_claimed',
                        'outbox_delivered',
                        'outbox_failed',
                        'outbox_retry_queued',
                        'outbox_dead_lettered'
                    )
                ),

            attempt_number INTEGER NOT NULL
                CHECK (attempt_number >= 0),

            idempotency_key TEXT NOT NULL
                CHECK (LENGTH(idempotency_key) = 64),

            worker_id TEXT,

            provider_name TEXT,
            provider_message_id TEXT,
            error_message TEXT,

            subject TEXT NOT NULL,
            body TEXT NOT NULL,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (
                delivery_id,
                event_type,
                attempt_number
            )
        );

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_notification_outbox_enqueued
        ON supplier_notification_outbox_events (
            delivery_id
        )
        WHERE event_type = 'outbox_enqueued';

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_notification_outbox_delivered
        ON supplier_notification_outbox_events (
            delivery_id
        )
        WHERE event_type = 'outbox_delivered';

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_supplier_notification_outbox_dead_lettered
        ON supplier_notification_outbox_events (
            delivery_id
        )
        WHERE event_type = 'outbox_dead_lettered';

        CREATE INDEX IF NOT EXISTS
            idx_supplier_notification_outbox_supplier
        ON supplier_notification_outbox_events (
            supplier_code,
            outbox_event_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_notification_outbox_delivery
        ON supplier_notification_outbox_events (
            delivery_id,
            outbox_event_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_supplier_notification_outbox_state
        ON supplier_notification_outbox_events (
            event_type,
            outbox_event_id
        );

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_notification_outbox_immutable_update
        BEFORE UPDATE ON supplier_notification_outbox_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_notification_outbox_events is append-only'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_supplier_notification_outbox_immutable_delete
        BEFORE DELETE ON supplier_notification_outbox_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'supplier_notification_outbox_events is append-only'
            );
        END;
        """
    )
