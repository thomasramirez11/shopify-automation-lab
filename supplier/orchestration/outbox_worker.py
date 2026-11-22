from __future__ import annotations

from supplier.orchestration.outbox_models import (
    NotificationOutboxEventType,
    NotificationOutboxState,
    NotificationOutboxWorkerResult,
)


class SupplierNotificationOutboxWorker:
    """
    Single-process durable notification worker.

    V2.7J intentionally does not implement multi-worker leasing yet.

    Restart safety:
    - ENQUEUED -> claim attempt 1
    - RETRY_QUEUED -> claim its queued attempt
    - CLAIMED -> resume the same attempt after interruption

    If an external provider accepted the message before the process crashed,
    the deterministic provider idempotency key prevents duplicate delivery.
    """

    def __init__(
        self,
        *,
        outbox_repository,
        delivery_service,
        worker_id: str = "notification-worker-1",
    ) -> None:
        if (
            not isinstance(
                worker_id,
                str,
            )
            or not worker_id.strip()
        ):
            raise ValueError(
                "worker_id must be a non-empty string."
            )

        self._outbox_repository = (
            outbox_repository
        )
        self._delivery_service = (
            delivery_service
        )
        self._worker_id = (
            worker_id.strip()
        )

    def process_pending(
        self,
        *,
        supplier_code: str,
        provider,
        limit: int = 100,
    ) -> NotificationOutboxWorkerResult:
        jobs = (
            self._outbox_repository
            .get_pending_jobs(
                supplier_code=(
                    supplier_code
                ),
                limit=limit,
            )
        )

        claimed = 0
        resumed = 0
        delivered = 0
        failed = 0
        skipped = 0

        for job in jobs:
            if (
                job.state
                == NotificationOutboxState.ENQUEUED
            ):
                attempt_number = 1

                _, created = (
                    self._outbox_repository
                    .append_event(
                        message=job.message,
                        event_type=(
                            NotificationOutboxEventType
                            .CLAIMED.value
                        ),
                        attempt_number=(
                            attempt_number
                        ),
                        worker_id=(
                            self._worker_id
                        ),
                        provider_name=(
                            provider.provider_name
                        ),
                    )
                )

                if created:
                    claimed += 1
                else:
                    resumed += 1

                delivery_result = (
                    self._delivery_service
                    .deliver_message(
                        message=job.message,
                        provider=provider,
                    )
                )

            elif (
                job.state
                == NotificationOutboxState.RETRY_QUEUED
            ):
                attempt_number = (
                    job.attempt_number
                )

                _, created = (
                    self._outbox_repository
                    .append_event(
                        message=job.message,
                        event_type=(
                            NotificationOutboxEventType
                            .CLAIMED.value
                        ),
                        attempt_number=(
                            attempt_number
                        ),
                        worker_id=(
                            self._worker_id
                        ),
                        provider_name=(
                            provider.provider_name
                        ),
                    )
                )

                if created:
                    claimed += 1
                else:
                    resumed += 1

                delivery_result = (
                    self._delivery_service
                    .retry_failed_message(
                        message=job.message,
                        provider=provider,
                    )
                )

            elif (
                job.state
                == NotificationOutboxState.CLAIMED
            ):
                attempt_number = (
                    job.attempt_number
                )
                resumed += 1

                if attempt_number == 1:
                    delivery_result = (
                        self._delivery_service
                        .deliver_message(
                            message=job.message,
                            provider=provider,
                        )
                    )
                else:
                    delivery_result = (
                        self._delivery_service
                        .retry_failed_message(
                            message=job.message,
                            provider=provider,
                        )
                    )

            else:
                continue

            if delivery_result.delivered:
                self._outbox_repository.append_event(
                    message=job.message,
                    event_type=(
                        NotificationOutboxEventType
                        .DELIVERED.value
                    ),
                    attempt_number=(
                        attempt_number
                    ),
                    worker_id=(
                        self._worker_id
                    ),
                    provider_name=(
                        provider.provider_name
                    ),
                    provider_message_id=(
                        delivery_result
                        .provider_message_id
                    ),
                )
                delivered += 1

            elif delivery_result.attempted:
                self._outbox_repository.append_event(
                    message=job.message,
                    event_type=(
                        NotificationOutboxEventType
                        .FAILED.value
                    ),
                    attempt_number=(
                        attempt_number
                    ),
                    worker_id=(
                        self._worker_id
                    ),
                    provider_name=(
                        provider.provider_name
                    ),
                    error_message=(
                        delivery_result
                        .error_message
                    ),
                )
                failed += 1

            else:
                skipped += 1

        return NotificationOutboxWorkerResult(
            jobs_seen=(
                len(jobs)
            ),
            jobs_claimed=claimed,
            jobs_resumed=resumed,
            delivered=delivered,
            failed=failed,
            skipped=skipped,
        )
