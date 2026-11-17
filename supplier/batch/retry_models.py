from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RetryPolicyError(ValueError):
    """Raised when retry policy or retry data is invalid."""


class RetryDecisionStatus(str, Enum):
    QUEUE = "queue"
    ALREADY_RECOVERED = "already_recovered"
    EXHAUSTED = "exhausted"
    NON_RETRYABLE = "non_retryable"


class RetryEventType(str, Enum):
    RETRY_QUEUED = "retry_queued"
    RETRY_STARTED = "retry_started"
    RETRY_SUCCEEDED = "retry_succeeded"
    RETRY_FAILED = "retry_failed"
    RETRY_EXHAUSTED = "retry_exhausted"
    RETRY_SKIPPED = "retry_skipped"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts_per_item: int = 3

    retryable_error_markers: tuple[str, ...] = (
        "applied=false",
        "timeout",
        "temporarily unavailable",
        "rate limit",
        "throttled",
    )

    def __post_init__(self) -> None:
        if (
            isinstance(
                self.max_attempts_per_item,
                bool,
            )
            or not isinstance(
                self.max_attempts_per_item,
                int,
            )
            or self.max_attempts_per_item < 1
        ):
            raise RetryPolicyError(
                "max_attempts_per_item must be an integer greater than zero."
            )

        if not self.retryable_error_markers:
            raise RetryPolicyError(
                "retryable_error_markers cannot be empty."
            )

        for marker in self.retryable_error_markers:
            if (
                not isinstance(marker, str)
                or not marker.strip()
            ):
                raise RetryPolicyError(
                    "retryable_error_markers must contain non-empty strings."
                )


@dataclass(frozen=True)
class FailedBatchItem:
    source_batch_id: str
    item_index: int
    operation_id: str

    shopify_variant_id: str
    shopify_sku: str

    before_quantity: int
    requested_quantity: int
    inventory_delta: int

    original_error_message: str


@dataclass(frozen=True)
class RetryDecision:
    retry_id: str
    status: RetryDecisionStatus

    source_batch_id: str
    item_index: int
    operation_id: str

    next_attempt_number: int | None
    prior_attempts: int
    max_attempts: int

    reason: str


@dataclass(frozen=True)
class RetryAuditEvent:
    retry_id: str
    source_batch_id: str
    item_index: int
    operation_id: str

    shopify_variant_id: str
    shopify_sku: str

    before_quantity: int
    requested_quantity: int
    inventory_delta: int

    attempt_number: int
    event_type: RetryEventType

    error_message: str | None = None

    def __post_init__(self) -> None:
        _require_sha256(
            "retry_id",
            self.retry_id,
        )
        _require_sha256(
            "source_batch_id",
            self.source_batch_id,
        )
        _require_sha256(
            "operation_id",
            self.operation_id,
        )

        if (
            isinstance(
                self.item_index,
                bool,
            )
            or not isinstance(
                self.item_index,
                int,
            )
            or self.item_index < 1
        ):
            raise RetryPolicyError(
                "item_index must be an integer greater than zero."
            )

        if (
            not isinstance(
                self.shopify_variant_id,
                str,
            )
            or not self.shopify_variant_id.startswith(
                "gid://shopify/ProductVariant/"
            )
        ):
            raise RetryPolicyError(
                "shopify_variant_id must be a Shopify ProductVariant GID."
            )

        if (
            not isinstance(
                self.shopify_sku,
                str,
            )
            or not self.shopify_sku.strip()
        ):
            raise RetryPolicyError(
                "shopify_sku must be a non-empty string."
            )

        _require_non_negative_integer(
            "before_quantity",
            self.before_quantity,
        )
        _require_non_negative_integer(
            "requested_quantity",
            self.requested_quantity,
        )

        if (
            isinstance(
                self.inventory_delta,
                bool,
            )
            or not isinstance(
                self.inventory_delta,
                int,
            )
        ):
            raise RetryPolicyError(
                "inventory_delta must be an integer."
            )

        if (
            isinstance(
                self.attempt_number,
                bool,
            )
            or not isinstance(
                self.attempt_number,
                int,
            )
            or self.attempt_number < 1
        ):
            raise RetryPolicyError(
                "attempt_number must be an integer greater than zero."
            )

        if (
            self.event_type
            in (
                RetryEventType.RETRY_FAILED,
                RetryEventType.RETRY_SKIPPED,
            )
            and not (
                isinstance(
                    self.error_message,
                    str,
                )
                and self.error_message.strip()
            )
        ):
            raise RetryPolicyError(
                f"{self.event_type.value} requires error_message."
            )


@dataclass(frozen=True)
class RetryAppendResult:
    retry_event_id: int
    created_new: bool


@dataclass(frozen=True)
class RetryQueueSummary:
    failed_items_seen: int
    queued: int
    already_recovered: int
    exhausted: int
    non_retryable: int


@dataclass(frozen=True)
class RetryExecutionSummary:
    queued_retries_seen: int
    attempted: int
    succeeded: int
    failed: int
    exhausted_now: int


@dataclass(frozen=True)
class StoredRetryEvent:
    retry_event_id: int

    retry_id: str
    source_batch_id: str
    item_index: int
    operation_id: str

    shopify_variant_id: str
    shopify_sku: str

    before_quantity: int
    requested_quantity: int
    inventory_delta: int

    attempt_number: int
    event_type: str

    error_message: str | None
    created_at: str


def _require_sha256(
    field_name: str,
    value,
) -> None:
    if (
        not isinstance(
            value,
            str,
        )
        or len(
            value.strip()
        ) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character
            in value.strip().lower()
        )
    ):
        raise RetryPolicyError(
            f"{field_name} must be a 64-character SHA-256 hex digest."
        )


def _require_non_negative_integer(
    field_name: str,
    value,
) -> None:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
    ):
        raise RetryPolicyError(
            f"{field_name} must be an integer."
        )

    if value < 0:
        raise RetryPolicyError(
            f"{field_name} cannot be negative."
        )
