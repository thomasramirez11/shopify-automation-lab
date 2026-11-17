from __future__ import annotations

from supplier.batch.retry_models import (
    RetryAuditEvent,
    RetryDecisionStatus,
    RetryEventType,
    RetryExecutionSummary,
    RetryPolicy,
    RetryQueueSummary,
)
from supplier.batch.retry_policy import (
    build_retry_id,
    evaluate_retry_decision,
)
from supplier.batch.retry_repository import (
    SupplierBatchRetryRepository,
)
from supplier.execution.models import (
    InventoryMutation,
)
from supplier.execution.ports import (
    InventoryMutationPort,
)


class SupplierBatchRetryService:
    """
    Queue and execute isolated recovery attempts for original failed items.

    Successful original batch items are never retried.
    """

    def __init__(
        self,
        *,
        repository: SupplierBatchRetryRepository,
        policy: RetryPolicy,
    ) -> None:
        self._repository = repository
        self._policy = policy

    def queue_eligible_failures(
        self,
    ) -> RetryQueueSummary:
        failed_items = (
            self._repository
            .discover_failed_items()
        )

        queued = 0
        recovered = 0
        exhausted = 0
        non_retryable = 0

        for failed_item in failed_items:
            retry_id = build_retry_id(
                failed_item
            )

            prior_attempts = (
                self._repository
                .count_attempts(
                    retry_id
                )
            )

            already_recovered = (
                self._repository
                .has_success(
                    retry_id
                )
            )

            already_exhausted = (
                self._repository
                .has_exhausted(
                    retry_id
                )
            )

            decision = evaluate_retry_decision(
                failed_item=failed_item,
                prior_attempts=(
                    prior_attempts
                ),
                recovered=(
                    already_recovered
                ),
                exhausted=(
                    already_exhausted
                ),
                policy=self._policy,
            )

            if (
                decision.status
                == RetryDecisionStatus.ALREADY_RECOVERED
            ):
                recovered += 1
                continue

            if (
                decision.status
                == RetryDecisionStatus.EXHAUSTED
            ):
                exhausted += 1

                attempt_number = max(
                    prior_attempts,
                    1,
                )

                self._repository.append(
                    self._event_from_failed_item(
                        failed_item=failed_item,
                        retry_id=retry_id,
                        attempt_number=(
                            attempt_number
                        ),
                        event_type=(
                            RetryEventType
                            .RETRY_EXHAUSTED
                        ),
                    )
                )
                continue

            if (
                decision.status
                == RetryDecisionStatus.NON_RETRYABLE
            ):
                non_retryable += 1

                self._repository.append(
                    self._event_from_failed_item(
                        failed_item=failed_item,
                        retry_id=retry_id,
                        attempt_number=max(
                            prior_attempts + 1,
                            1,
                        ),
                        event_type=(
                            RetryEventType
                            .RETRY_SKIPPED
                        ),
                        error_message=(
                            "Original failure is not classified "
                            "as retryable."
                        ),
                    )
                )
                continue

            append_result = (
                self._repository.append(
                    self._event_from_failed_item(
                        failed_item=failed_item,
                        retry_id=retry_id,
                        attempt_number=(
                            decision.next_attempt_number
                        ),
                        event_type=(
                            RetryEventType
                            .RETRY_QUEUED
                        ),
                    )
                )
            )

            if append_result.created_new:
                queued += 1

        return RetryQueueSummary(
            failed_items_seen=(
                len(failed_items)
            ),
            queued=queued,
            already_recovered=recovered,
            exhausted=exhausted,
            non_retryable=non_retryable,
        )

    def execute_queued_retries(
        self,
        *,
        inventory_port: InventoryMutationPort,
    ) -> RetryExecutionSummary:
        queued_events = (
            self._repository
            .get_queued_attempts()
        )

        attempted = 0
        succeeded = 0
        failed = 0
        exhausted_now = 0

        for queued in queued_events:
            attempted += 1

            self._repository.append(
                self._event_from_stored(
                    stored=queued,
                    event_type=(
                        RetryEventType
                        .RETRY_STARTED
                    ),
                )
            )

            mutation = InventoryMutation(
                shopify_variant_id=(
                    queued.shopify_variant_id
                ),
                shopify_sku=(
                    queued.shopify_sku
                ),
                inventory_quantity=(
                    queued.requested_quantity
                ),
            )

            result = (
                inventory_port
                .set_inventory(
                    mutation
                )
            )

            if result.applied:
                succeeded += 1

                self._repository.append(
                    self._event_from_stored(
                        stored=queued,
                        event_type=(
                            RetryEventType
                            .RETRY_SUCCEEDED
                        ),
                    )
                )
                continue

            failed += 1

            self._repository.append(
                self._event_from_stored(
                    stored=queued,
                    event_type=(
                        RetryEventType
                        .RETRY_FAILED
                    ),
                    error_message=(
                        "Retry inventory mutation adapter "
                        "reported applied=False."
                    ),
                )
            )

            if (
                queued.attempt_number
                >= self._policy.max_attempts_per_item
            ):
                exhausted_now += 1

                self._repository.append(
                    self._event_from_stored(
                        stored=queued,
                        event_type=(
                            RetryEventType
                            .RETRY_EXHAUSTED
                        ),
                    )
                )

        return RetryExecutionSummary(
            queued_retries_seen=(
                len(queued_events)
            ),
            attempted=attempted,
            succeeded=succeeded,
            failed=failed,
            exhausted_now=(
                exhausted_now
            ),
        )

    def _event_from_failed_item(
        self,
        *,
        failed_item,
        retry_id: str,
        attempt_number: int,
        event_type: RetryEventType,
        error_message: str | None = None,
    ) -> RetryAuditEvent:
        return RetryAuditEvent(
            retry_id=retry_id,
            source_batch_id=(
                failed_item.source_batch_id
            ),
            item_index=(
                failed_item.item_index
            ),
            operation_id=(
                failed_item.operation_id
            ),
            shopify_variant_id=(
                failed_item.shopify_variant_id
            ),
            shopify_sku=(
                failed_item.shopify_sku
            ),
            before_quantity=(
                failed_item.before_quantity
            ),
            requested_quantity=(
                failed_item.requested_quantity
            ),
            inventory_delta=(
                failed_item.inventory_delta
            ),
            attempt_number=(
                attempt_number
            ),
            event_type=(
                event_type
            ),
            error_message=(
                error_message
            ),
        )

    def _event_from_stored(
        self,
        *,
        stored,
        event_type: RetryEventType,
        error_message: str | None = None,
    ) -> RetryAuditEvent:
        return RetryAuditEvent(
            retry_id=(
                stored.retry_id
            ),
            source_batch_id=(
                stored.source_batch_id
            ),
            item_index=(
                stored.item_index
            ),
            operation_id=(
                stored.operation_id
            ),
            shopify_variant_id=(
                stored.shopify_variant_id
            ),
            shopify_sku=(
                stored.shopify_sku
            ),
            before_quantity=(
                stored.before_quantity
            ),
            requested_quantity=(
                stored.requested_quantity
            ),
            inventory_delta=(
                stored.inventory_delta
            ),
            attempt_number=(
                stored.attempt_number
            ),
            event_type=(
                event_type
            ),
            error_message=(
                error_message
            ),
        )
