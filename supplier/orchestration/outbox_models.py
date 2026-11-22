from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from supplier.orchestration.notification_models import (
    NotificationChannel,
    NotificationMessage,
)


class NotificationOutboxError(ValueError):
    """Raised when durable outbox state is unsafe or inconsistent."""


class NotificationOutboxEventType(str, Enum):
    ENQUEUED = "outbox_enqueued"
    CLAIMED = "outbox_claimed"
    DELIVERED = "outbox_delivered"
    FAILED = "outbox_failed"
    RETRY_QUEUED = "outbox_retry_queued"
    DEAD_LETTERED = "outbox_dead_lettered"


class NotificationOutboxState(str, Enum):
    ENQUEUED = "enqueued"
    CLAIMED = "claimed"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRY_QUEUED = "retry_queued"
    DEAD_LETTERED = "dead_lettered"


@dataclass(frozen=True)
class StoredNotificationOutboxEvent:
    outbox_event_id: int

    delivery_id: str
    route_event_id: int

    incident_id: str
    supplier_code: str

    route: str
    channel: str

    event_type: str
    attempt_number: int

    idempotency_key: str

    worker_id: str | None

    provider_name: str | None
    provider_message_id: str | None
    error_message: str | None

    subject: str
    body: str

    created_at: str

    def to_message(self) -> NotificationMessage:
        return NotificationMessage(
            delivery_id=self.delivery_id,
            idempotency_key=self.idempotency_key,
            route_event_id=self.route_event_id,
            incident_id=self.incident_id,
            supplier_code=self.supplier_code,
            route=self.route,
            channel=NotificationChannel(
                self.channel
            ),
            subject=self.subject,
            body=self.body,
        )


@dataclass(frozen=True)
class NotificationOutboxJob:
    delivery_id: str
    state: NotificationOutboxState

    attempt_number: int

    message: NotificationMessage

    latest_event_id: int
    latest_created_at: str

    error_message: str | None = None

    @property
    def terminal(self) -> bool:
        return self.state in {
            NotificationOutboxState.DELIVERED,
            NotificationOutboxState.DEAD_LETTERED,
        }


@dataclass(frozen=True)
class NotificationOutboxEnqueueResult:
    alert_routes_seen: int
    messages_planned: int

    jobs_enqueued: int
    jobs_already_present: int


@dataclass(frozen=True)
class NotificationOutboxWorkerResult:
    jobs_seen: int
    jobs_claimed: int
    jobs_resumed: int

    delivered: int
    failed: int
    skipped: int


@dataclass(frozen=True)
class NotificationOutboxRecoveryResult:
    failed_jobs_seen: int

    retries_queued: int
    dead_lettered: int
    already_recovered: int
