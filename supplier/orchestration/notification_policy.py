from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from supplier.orchestration.notification_models import NotificationChannel, NotificationDeliveryError, NotificationMessage


@dataclass(frozen=True)
class NotificationDeliveryPolicy:
    operator_review_channels: tuple[NotificationChannel, ...] = (NotificationChannel.SLACK,)
    immediate_alert_channels: tuple[NotificationChannel, ...] = (
        NotificationChannel.EMAIL,
        NotificationChannel.SLACK,
        NotificationChannel.WEBHOOK,
    )
    recovery_notice_channels: tuple[NotificationChannel, ...] = (
        NotificationChannel.EMAIL,
        NotificationChannel.SLACK,
    )

    def __post_init__(self) -> None:
        for name in ("operator_review_channels", "immediate_alert_channels", "recovery_notice_channels"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not values:
                raise NotificationDeliveryError(f"{name} must be a non-empty tuple.")
            if len(values) != len(set(values)):
                raise NotificationDeliveryError(f"{name} cannot contain duplicate channels.")
            if not all(isinstance(value, NotificationChannel) for value in values):
                raise NotificationDeliveryError(f"{name} must contain NotificationChannel values.")

    @property
    def fingerprint(self) -> str:
        payload = {
            "operator_review_channels": [x.value for x in self.operator_review_channels],
            "immediate_alert_channels": [x.value for x in self.immediate_alert_channels],
            "recovery_notice_channels": [x.value for x in self.recovery_notice_channels],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


DEFAULT_NOTIFICATION_DELIVERY_POLICY = NotificationDeliveryPolicy()


def build_notification_messages(*, alert_route, policy: NotificationDeliveryPolicy = DEFAULT_NOTIFICATION_DELIVERY_POLICY) -> tuple[NotificationMessage, ...]:
    if alert_route.route == "dashboard":
        channels = ()
    elif alert_route.route == "operator_review":
        channels = policy.operator_review_channels
    elif alert_route.route == "immediate_alert":
        channels = policy.immediate_alert_channels
    elif alert_route.route == "recovery_notice":
        channels = policy.recovery_notice_channels
    else:
        raise NotificationDeliveryError(f"Unsupported alert route: {alert_route.route!r}")

    subject = f"[{alert_route.severity.upper()}] Shopify Automation Lab incident {alert_route.incident_id[:12]}"
    body = (
        f"Supplier: {alert_route.supplier_code}\n"
        f"Incident: {alert_route.incident_id}\n"
        f"Source event: {alert_route.source_event_type}\n"
        f"Severity: {alert_route.severity}\n"
        f"Route: {alert_route.route}"
    )

    messages = []
    for channel in channels:
        identity = json.dumps(
            {
                "route_event_id": alert_route.route_event_id,
                "incident_id": alert_route.incident_id,
                "route": alert_route.route,
                "channel": channel.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        delivery_id = hashlib.sha256(("delivery:" + identity).encode("utf-8")).hexdigest()
        idempotency_key = hashlib.sha256(("notification-idempotency:" + delivery_id).encode("utf-8")).hexdigest()
        messages.append(
            NotificationMessage(
                delivery_id=delivery_id,
                idempotency_key=idempotency_key,
                route_event_id=alert_route.route_event_id,
                incident_id=alert_route.incident_id,
                supplier_code=alert_route.supplier_code,
                route=alert_route.route,
                channel=channel,
                subject=subject,
                body=body,
            )
        )
    return tuple(messages)
