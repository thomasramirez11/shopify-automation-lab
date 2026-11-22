from __future__ import annotations

from supplier.orchestration.notification_models import (
    NotificationDeliveryError,
    NotificationDeliveryEventType,
    NotificationDeliveryResult,
    NotificationDeliveryScanResult,
    NotificationRetryPolicy,
    NotificationRouteDeliveryResult,
)
from supplier.orchestration.notification_policy import DEFAULT_NOTIFICATION_DELIVERY_POLICY, build_notification_messages


class SupplierNotificationDeliveryService:
    def __init__(self, *, alert_repository, delivery_repository, delivery_policy=DEFAULT_NOTIFICATION_DELIVERY_POLICY, retry_policy=NotificationRetryPolicy()) -> None:
        self._alert_repository = alert_repository
        self._delivery_repository = delivery_repository
        self._delivery_policy = delivery_policy
        self._retry_policy = retry_policy

    def deliver_alert_route(self, *, alert_route, provider) -> NotificationRouteDeliveryResult:
        messages = build_notification_messages(alert_route=alert_route, policy=self._delivery_policy)
        results = tuple(self.deliver_message(message=message, provider=provider) for message in messages)
        return NotificationRouteDeliveryResult(
            route_event_id=alert_route.route_event_id,
            messages_planned=len(messages),
            attempted=sum(result.attempted for result in results),
            delivered=sum(result.delivered for result in results),
            failed=sum(result.attempted and not result.delivered for result in results),
            skipped=sum(result.skipped for result in results),
            results=results,
        )

    def deliver_message(self, *, message, provider) -> NotificationDeliveryResult:
        delivered = self._delivery_repository.get_delivered_event(message.delivery_id)
        if delivered is not None:
            return NotificationDeliveryResult(
                message=message, attempted=False, delivered=True, skipped=True,
                attempt_number=delivered.attempt_number,
                provider_message_id=delivered.provider_message_id,
                error_message=None, reason="already_delivered",
            )

        latest = self._delivery_repository.get_latest_outcome(message.delivery_id)
        if latest is not None and latest.event_type == "delivery_failed":
            return NotificationDeliveryResult(
                message=message, attempted=False, delivered=False, skipped=True,
                attempt_number=latest.attempt_number,
                provider_message_id=None, error_message=latest.error_message,
                reason="failed_delivery_requires_explicit_retry",
            )

        return self._attempt(message=message, provider=provider, attempt_number=1)

    def retry_failed_message(self, *, message, provider) -> NotificationDeliveryResult:
        delivered = self._delivery_repository.get_delivered_event(message.delivery_id)
        if delivered is not None:
            return NotificationDeliveryResult(
                message=message, attempted=False, delivered=True, skipped=True,
                attempt_number=delivered.attempt_number,
                provider_message_id=delivered.provider_message_id,
                error_message=None, reason="already_delivered",
            )

        latest = self._delivery_repository.get_latest_outcome(message.delivery_id)
        if latest is None or latest.event_type != "delivery_failed":
            raise NotificationDeliveryError("Notification retry requires a previous delivery_failed event.")

        next_attempt = latest.attempt_number + 1
        if next_attempt > self._retry_policy.max_attempts:
            raise NotificationDeliveryError("Notification retry limit exhausted.")

        self._delivery_repository.append_event(
            message=message,
            event_type=NotificationDeliveryEventType.RETRY_QUEUED.value,
            attempt_number=next_attempt,
            provider_name=provider.provider_name,
        )
        return self._attempt(message=message, provider=provider, attempt_number=next_attempt)

    def deliver_existing_alert_routes(self, *, supplier_code: str, provider, limit: int = 100) -> NotificationDeliveryScanResult:
        routes = tuple(reversed(self._alert_repository.get_recent_routes(supplier_code=supplier_code, limit=limit)))
        route_results = [self.deliver_alert_route(alert_route=route, provider=provider) for route in routes]
        return NotificationDeliveryScanResult(
            alert_routes_seen=len(routes),
            external_messages_planned=sum(result.messages_planned for result in route_results),
            attempted=sum(result.attempted for result in route_results),
            delivered=sum(result.delivered for result in route_results),
            failed=sum(result.failed for result in route_results),
            skipped=sum(result.skipped for result in route_results),
        )

    def _attempt(self, *, message, provider, attempt_number: int) -> NotificationDeliveryResult:
        self._delivery_repository.append_event(
            message=message,
            event_type=NotificationDeliveryEventType.DELIVERY_STARTED.value,
            attempt_number=attempt_number,
            provider_name=provider.provider_name,
        )
        receipt = provider.send(message)
        if receipt.delivered:
            self._delivery_repository.append_event(
                message=message,
                event_type=NotificationDeliveryEventType.DELIVERY_DELIVERED.value,
                attempt_number=attempt_number,
                provider_name=receipt.provider_name,
                provider_message_id=receipt.provider_message_id,
            )
            return NotificationDeliveryResult(
                message=message, attempted=True, delivered=True, skipped=False,
                attempt_number=attempt_number, provider_message_id=receipt.provider_message_id,
                error_message=None, reason="provider_delivered",
            )

        self._delivery_repository.append_event(
            message=message,
            event_type=NotificationDeliveryEventType.DELIVERY_FAILED.value,
            attempt_number=attempt_number,
            provider_name=receipt.provider_name,
            error_message=receipt.error_message,
        )
        return NotificationDeliveryResult(
            message=message, attempted=True, delivered=False, skipped=False,
            attempt_number=attempt_number, provider_message_id=None,
            error_message=receipt.error_message, reason="provider_failed",
        )
