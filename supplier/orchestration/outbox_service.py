from __future__ import annotations

from supplier.orchestration.notification_models import (
    NotificationRetryPolicy,
)
from supplier.orchestration.notification_policy import (
    DEFAULT_NOTIFICATION_DELIVERY_POLICY,
    build_notification_messages,
)
from supplier.orchestration.outbox_models import (
    NotificationOutboxEnqueueResult,
    NotificationOutboxEventType,
    NotificationOutboxRecoveryResult,
)


class SupplierNotificationOutboxService:
    """
    Durable notification intent + explicit recovery queue.
    """

    def __init__(
        self,
        *,
        alert_repository,
        outbox_repository,
        delivery_policy=(
            DEFAULT_NOTIFICATION_DELIVERY_POLICY
        ),
        retry_policy=(
            NotificationRetryPolicy()
        ),
    ) -> None:
        self._alert_repository = (
            alert_repository
        )
        self._outbox_repository = (
            outbox_repository
        )
        self._delivery_policy = (
            delivery_policy
        )
        self._retry_policy = (
            retry_policy
        )

    def enqueue_alert_route(
        self,
        alert_route,
    ) -> NotificationOutboxEnqueueResult:
        messages = build_notification_messages(
            alert_route=alert_route,
            policy=self._delivery_policy,
        )

        enqueued = 0
        existing = 0

        for message in messages:
            _, created = (
                self._outbox_repository
                .enqueue(
                    message
                )
            )

            if created:
                enqueued += 1
            else:
                existing += 1

        return NotificationOutboxEnqueueResult(
            alert_routes_seen=1,
            messages_planned=(
                len(messages)
            ),
            jobs_enqueued=enqueued,
            jobs_already_present=existing,
        )

    def enqueue_existing_alert_routes(
        self,
        *,
        supplier_code: str,
        limit: int = 100,
    ) -> NotificationOutboxEnqueueResult:
        routes = tuple(
            reversed(
                self._alert_repository
                .get_recent_routes(
                    supplier_code=(
                        supplier_code
                    ),
                    limit=limit,
                )
            )
        )

        planned = 0
        enqueued = 0
        existing = 0

        for route in routes:
            result = self.enqueue_alert_route(
                route
            )

            planned += (
                result.messages_planned
            )
            enqueued += (
                result.jobs_enqueued
            )
            existing += (
                result.jobs_already_present
            )

        return NotificationOutboxEnqueueResult(
            alert_routes_seen=(
                len(routes)
            ),
            messages_planned=planned,
            jobs_enqueued=enqueued,
            jobs_already_present=existing,
        )

    def recover_failed_jobs(
        self,
        *,
        supplier_code: str,
        provider_name: str,
        limit: int = 100,
    ) -> NotificationOutboxRecoveryResult:
        failed_jobs = (
            self._outbox_repository
            .get_failed_jobs(
                supplier_code=(
                    supplier_code
                ),
                limit=limit,
            )
        )

        retries_queued = 0
        dead_lettered = 0
        already_recovered = 0

        for job in failed_jobs:
            next_attempt = (
                job.attempt_number
                + 1
            )

            if (
                next_attempt
                > self._retry_policy
                .max_attempts
            ):
                _, created = (
                    self._outbox_repository
                    .append_event(
                        message=job.message,
                        event_type=(
                            NotificationOutboxEventType
                            .DEAD_LETTERED.value
                        ),
                        attempt_number=(
                            job.attempt_number
                        ),
                        provider_name=(
                            provider_name
                        ),
                        error_message=(
                            job.error_message
                            or "Notification retry limit exhausted."
                        ),
                    )
                )

                if created:
                    dead_lettered += 1
                else:
                    already_recovered += 1

                continue

            _, created = (
                self._outbox_repository
                .append_event(
                    message=job.message,
                    event_type=(
                        NotificationOutboxEventType
                        .RETRY_QUEUED.value
                    ),
                    attempt_number=(
                        next_attempt
                    ),
                    provider_name=(
                        provider_name
                    ),
                    error_message=(
                        job.error_message
                    ),
                )
            )

            if created:
                retries_queued += 1
            else:
                already_recovered += 1

        return NotificationOutboxRecoveryResult(
            failed_jobs_seen=(
                len(failed_jobs)
            ),
            retries_queued=(
                retries_queued
            ),
            dead_lettered=(
                dead_lettered
            ),
            already_recovered=(
                already_recovered
            ),
        )
