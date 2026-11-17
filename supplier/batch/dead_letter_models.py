from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DeadLetterError(ValueError):
    """Raised when dead-letter data or human escalation input is invalid."""


class DeadLetterReason(str, Enum):
    RETRY_EXHAUSTED = "retry_exhausted"
    NON_RETRYABLE_FAILURE = "non_retryable_failure"


class DeadLetterEventType(str, Enum):
    CASE_OPENED = "case_opened"
    CASE_ACKNOWLEDGED = "case_acknowledged"


@dataclass(frozen=True)
class DeadLetterCandidate:
    source_retry_id: str
    source_batch_id: str
    item_index: int
    operation_id: str

    shopify_variant_id: str
    shopify_sku: str
    requested_quantity: int

    reason: DeadLetterReason


@dataclass(frozen=True)
class DeadLetterAuditEvent:
    case_id: str

    source_retry_id: str
    source_batch_id: str
    item_index: int
    operation_id: str

    shopify_variant_id: str
    shopify_sku: str
    requested_quantity: int

    reason: DeadLetterReason
    event_type: DeadLetterEventType

    actor: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("case_id", self.case_id),
            ("source_retry_id", self.source_retry_id),
            ("source_batch_id", self.source_batch_id),
            ("operation_id", self.operation_id),
        ):
            _require_sha256(
                field_name,
                value,
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
            raise DeadLetterError(
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
            raise DeadLetterError(
                "shopify_variant_id must be a Shopify ProductVariant GID."
            )

        _require_text(
            "shopify_sku",
            self.shopify_sku,
        )
        _require_non_negative_integer(
            "requested_quantity",
            self.requested_quantity,
        )

        if (
            self.event_type
            == DeadLetterEventType.CASE_ACKNOWLEDGED
        ):
            _require_text(
                "actor",
                self.actor,
            )
            _require_text(
                "note",
                self.note,
            )


@dataclass(frozen=True)
class StoredDeadLetterEvent:
    dead_letter_event_id: int

    case_id: str
    source_retry_id: str
    source_batch_id: str
    item_index: int
    operation_id: str

    shopify_variant_id: str
    shopify_sku: str
    requested_quantity: int

    reason_code: str
    event_type: str

    actor: str | None
    note: str | None
    created_at: str


@dataclass(frozen=True)
class DeadLetterAppendResult:
    dead_letter_event_id: int
    created_new: bool


@dataclass(frozen=True)
class DeadLetterScanSummary:
    escalation_candidates_seen: int
    cases_opened: int
    already_open: int


@dataclass(frozen=True)
class DeadLetterCaseView:
    case_id: str
    source_retry_id: str
    source_batch_id: str
    item_index: int
    operation_id: str

    shopify_variant_id: str
    shopify_sku: str
    requested_quantity: int

    reason_code: str
    status: str

    opened_at: str
    acknowledged_at: str | None
    acknowledged_by: str | None
    acknowledgement_note: str | None


def _require_text(
    field_name: str,
    value,
) -> None:
    if (
        not isinstance(
            value,
            str,
        )
        or not value.strip()
    ):
        raise DeadLetterError(
            f"{field_name} must be a non-empty string."
        )


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
        raise DeadLetterError(
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
        raise DeadLetterError(
            f"{field_name} must be an integer."
        )

    if value < 0:
        raise DeadLetterError(
            f"{field_name} cannot be negative."
        )
