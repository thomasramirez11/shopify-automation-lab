from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NotificationDeliveryError(ValueError):
    pass


class NotificationChannel(str, Enum):
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"


class NotificationDeliveryEventType(str, Enum):
    DELIVERY_STARTED = "delivery_started"
    DELIVERY_DELIVERED = "delivery_delivered"
    DELIVERY_FAILED = "delivery_failed"
    RETRY_QUEUED = "retry_queued"


@dataclass(frozen=True)
class NotificationMessage:
    delivery_id: str
    idempotency_key: str
    route_event_id: int
    incident_id: str
    supplier_code: str
    route: str
    channel: NotificationChannel
    subject: str
    body: str


@dataclass(frozen=True)
class NotificationProviderReceipt:
    delivered: bool
    provider_name: str
    provider_message_id: str | None = None
    error_message: str | None = None
    deduplicated: bool = False

    def __post_init__(self) -> None:
        if self.delivered:
            if not self.provider_message_id:
                raise NotificationDeliveryError("Delivered receipt requires provider_message_id.")
            if self.error_message is not None:
                raise NotificationDeliveryError("Delivered receipt cannot contain error_message.")
        elif not self.error_message:
            raise NotificationDeliveryError("Failed receipt requires error_message.")


@dataclass(frozen=True)
class StoredNotificationDeliveryEvent:
    delivery_event_id: int
    delivery_id: str
    route_event_id: int
    incident_id: str
    supplier_code: str
    route: str
    channel: str
    event_type: str
    attempt_number: int
    idempotency_key: str
    provider_name: str
    provider_message_id: str | None
    error_message: str | None
    subject: str
    body: str
    created_at: str


@dataclass(frozen=True)
class NotificationDeliveryResult:
    message: NotificationMessage
    attempted: bool
    delivered: bool
    skipped: bool
    attempt_number: int
    provider_message_id: str | None
    error_message: str | None
    reason: str


@dataclass(frozen=True)
class NotificationRouteDeliveryResult:
    route_event_id: int
    messages_planned: int
    attempted: int
    delivered: int
    failed: int
    skipped: int
    results: tuple[NotificationDeliveryResult, ...]


@dataclass(frozen=True)
class NotificationDeliveryScanResult:
    alert_routes_seen: int
    external_messages_planned: int
    attempted: int
    delivered: int
    failed: int
    skipped: int


@dataclass(frozen=True)
class NotificationRetryPolicy:
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise NotificationDeliveryError("max_attempts must be an integer greater than zero.")
