from __future__ import annotations

import hashlib

from supplier.batch.retry_models import (
    FailedBatchItem,
    RetryDecision,
    RetryDecisionStatus,
    RetryPolicy,
)


def build_retry_id(
    failed_item: FailedBatchItem,
) -> str:
    """
    Deterministic identity for recovery of one original failed operation.
    """

    payload = (
        "supplier-retry:"
        + failed_item.operation_id
    )

    return hashlib.sha256(
        payload.encode(
            "utf-8"
        )
    ).hexdigest()


def evaluate_retry_decision(
    *,
    failed_item: FailedBatchItem,
    prior_attempts: int,
    recovered: bool,
    exhausted: bool,
    policy: RetryPolicy,
) -> RetryDecision:
    retry_id = build_retry_id(
        failed_item
    )

    if recovered:
        return RetryDecision(
            retry_id=retry_id,
            status=(
                RetryDecisionStatus
                .ALREADY_RECOVERED
            ),
            source_batch_id=(
                failed_item.source_batch_id
            ),
            item_index=(
                failed_item.item_index
            ),
            operation_id=(
                failed_item.operation_id
            ),
            next_attempt_number=None,
            prior_attempts=(
                prior_attempts
            ),
            max_attempts=(
                policy.max_attempts_per_item
            ),
            reason="retry_already_succeeded",
        )

    if (
        exhausted
        or prior_attempts
        >= policy.max_attempts_per_item
    ):
        return RetryDecision(
            retry_id=retry_id,
            status=(
                RetryDecisionStatus.EXHAUSTED
            ),
            source_batch_id=(
                failed_item.source_batch_id
            ),
            item_index=(
                failed_item.item_index
            ),
            operation_id=(
                failed_item.operation_id
            ),
            next_attempt_number=None,
            prior_attempts=(
                prior_attempts
            ),
            max_attempts=(
                policy.max_attempts_per_item
            ),
            reason="retry_budget_exhausted",
        )

    error_text = (
        failed_item
        .original_error_message
        .lower()
    )

    retryable = any(
        marker.lower() in error_text
        for marker
        in policy.retryable_error_markers
    )

    if not retryable:
        return RetryDecision(
            retry_id=retry_id,
            status=(
                RetryDecisionStatus
                .NON_RETRYABLE
            ),
            source_batch_id=(
                failed_item.source_batch_id
            ),
            item_index=(
                failed_item.item_index
            ),
            operation_id=(
                failed_item.operation_id
            ),
            next_attempt_number=None,
            prior_attempts=(
                prior_attempts
            ),
            max_attempts=(
                policy.max_attempts_per_item
            ),
            reason="failure_not_retryable",
        )

    return RetryDecision(
        retry_id=retry_id,
        status=(
            RetryDecisionStatus.QUEUE
        ),
        source_batch_id=(
            failed_item.source_batch_id
        ),
        item_index=(
            failed_item.item_index
        ),
        operation_id=(
            failed_item.operation_id
        ),
        next_attempt_number=(
            prior_attempts + 1
        ),
        prior_attempts=(
            prior_attempts
        ),
        max_attempts=(
            policy.max_attempts_per_item
        ),
        reason="retryable_failure_within_budget",
    )
