from __future__ import annotations

from database.connection import get_db_connection
from database.supplier_notification_delivery_schema import ensure_supplier_notification_delivery_schema
from supplier.orchestration.notification_models import StoredNotificationDeliveryEvent


class SupplierNotificationDeliveryRepository:
    def __init__(self, *, connection_factory=get_db_connection) -> None:
        self._connection_factory = connection_factory

    def ensure_schema(self) -> None:
        with self._connection_factory() as connection:
            ensure_supplier_notification_delivery_schema(connection)

    def append_event(self, *, message, event_type: str, attempt_number: int, provider_name: str, provider_message_id=None, error_message=None):
        with self._connection_factory() as connection:
            ensure_supplier_notification_delivery_schema(connection)
            cursor = connection.execute(
                """
                INSERT INTO supplier_notification_delivery_events (
                    delivery_id, route_event_id, incident_id, supplier_code,
                    route, channel, event_type, attempt_number,
                    idempotency_key, provider_name, provider_message_id,
                    error_message, subject, body
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (delivery_id, event_type, attempt_number) DO NOTHING;
                """,
                (
                    message.delivery_id, message.route_event_id, message.incident_id,
                    message.supplier_code, message.route, message.channel.value,
                    event_type, attempt_number, message.idempotency_key, provider_name,
                    provider_message_id, error_message, message.subject, message.body,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM supplier_notification_delivery_events
                WHERE delivery_id = ? AND event_type = ? AND attempt_number = ?;
                """,
                (message.delivery_id, event_type, attempt_number),
            ).fetchone()
            if row is None:
                raise RuntimeError("Delivery event could not be read after append.")
            return StoredNotificationDeliveryEvent(**dict(row)), cursor.rowcount == 1

    def get_events(self, delivery_id: str):
        with self._connection_factory() as connection:
            ensure_supplier_notification_delivery_schema(connection)
            rows = connection.execute(
                "SELECT * FROM supplier_notification_delivery_events WHERE delivery_id = ? ORDER BY delivery_event_id;",
                (delivery_id,),
            ).fetchall()
            return [StoredNotificationDeliveryEvent(**dict(row)) for row in rows]

    def get_delivered_event(self, delivery_id: str):
        for event in self.get_events(delivery_id):
            if event.event_type == "delivery_delivered":
                return event
        return None

    def get_latest_outcome(self, delivery_id: str):
        with self._connection_factory() as connection:
            ensure_supplier_notification_delivery_schema(connection)
            row = connection.execute(
                """
                SELECT * FROM supplier_notification_delivery_events
                WHERE delivery_id = ? AND event_type IN ('delivery_delivered','delivery_failed')
                ORDER BY delivery_event_id DESC LIMIT 1;
                """,
                (delivery_id,),
            ).fetchone()
            return StoredNotificationDeliveryEvent(**dict(row)) if row is not None else None

    def get_recent_events(self, *, supplier_code: str, limit: int = 100):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer.")
        with self._connection_factory() as connection:
            ensure_supplier_notification_delivery_schema(connection)
            rows = connection.execute(
                """
                SELECT * FROM supplier_notification_delivery_events
                WHERE supplier_code = ? ORDER BY delivery_event_id DESC LIMIT ?;
                """,
                (supplier_code, limit),
            ).fetchall()
            return [StoredNotificationDeliveryEvent(**dict(row)) for row in rows]

    def count_delivered(self, supplier_code: str) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_notification_delivery_schema(connection)
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM supplier_notification_delivery_events WHERE supplier_code = ? AND event_type = 'delivery_delivered';",
                (supplier_code,),
            ).fetchone()
            return int(row["count"])

    def count_failed(self, supplier_code: str) -> int:
        with self._connection_factory() as connection:
            ensure_supplier_notification_delivery_schema(connection)
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM supplier_notification_delivery_events WHERE supplier_code = ? AND event_type = 'delivery_failed';",
                (supplier_code,),
            ).fetchone()
            return int(row["count"])
