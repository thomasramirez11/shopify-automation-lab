from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CaseResolutionError(ValueError):
    """Raised when case-resolution lifecycle rules are violated."""


class ResolutionCode(str, Enum):
    SUPPLIER_FIXED = "supplier_fixed"
    CREDENTIALS_FIXED = "credentials_fixed"
    CONFIGURATION_FIXED = "configuration_fixed"
    MANUAL_DATA_CORRECTION = "manual_data_correction"
    OTHER = "other"


class ResolutionEventType(str, Enum):
    RESOLUTION_RECORDED = "resolution_recorded"
    REENTRY_AUTHORIZED = "reentry_authorized"
    REENTRY_STARTED = "reentry_started"
    REENTRY_SUCCEEDED = "reentry_succeeded"
    REENTRY_FAILED = "reentry_failed"
    CASE_CLOSED = "case_closed"


@dataclass(frozen=True)
class AcknowledgedDeadLetterCase:
    case_id: str
    source_retry_id: str
    source_batch_id: str
    operation_id: str

    shopify_variant_id: str
    shopify_sku: str
    requested_quantity: int

    reason_code: str

    acknowledged_by: str
    acknowledgement_note: str


@dataclass(frozen=True)
class CaseResolutionEvent:
    case_id: str
    resolution_fingerprint: str

    event_type: ResolutionEventType
    resolution_code: ResolutionCode

    actor: str
    note: str

    shopify_variant_id: str
    shopify_sku: str
    requested_quantity: int

    error_message: str | None = None

    def __post_init__(self) -> None:
        _require_sha256(
            "case_id",
            self.case_id,
        )
        _require_sha256(
            "resolution_fingerprint",
            self.resolution_fingerprint,
        )

        _require_text(
            "actor",
            self.actor,
        )
        _require_text(
            "note",
            self.note,
        )
        _require_text(
            "shopify_sku",
            self.shopify_sku,
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
            raise CaseResolutionError(
                "shopify_variant_id must be a Shopify ProductVariant GID."
            )

        if (
            isinstance(
                self.requested_quantity,
                bool,
            )
            or not isinstance(
                self.requested_quantity,
                int,
            )
        ):
            raise CaseResolutionError(
                "requested_quantity must be an integer."
            )

        if self.requested_quantity < 0:
            raise CaseResolutionError(
                "requested_quantity cannot be negative."
            )

        if (
            self.event_type
            == ResolutionEventType.REENTRY_FAILED
            and not (
                isinstance(
                    self.error_message,
                    str,
                )
                and self.error_message.strip()
            )
        ):
            raise CaseResolutionError(
                "reentry_failed requires error_message."
            )


@dataclass(frozen=True)
class StoredCaseResolutionEvent:
    resolution_event_id: int

    case_id: str
    resolution_fingerprint: str

    event_type: str
    resolution_code: str

    actor: str
    note: str

    shopify_variant_id: str
    shopify_sku: str
    requested_quantity: int

    error_message: str | None
    created_at: str


@dataclass(frozen=True)
class ResolutionAppendResult:
    resolution_event_id: int
    created_new: bool


@dataclass(frozen=True)
class ResolutionRecord:
    case_id: str
    resolution_fingerprint: str
    resolution_code: ResolutionCode

    actor: str
    note: str

    shopify_variant_id: str
    shopify_sku: str
    requested_quantity: int


@dataclass(frozen=True)
class ReentryExecutionResult:
    case_id: str
    resolution_fingerprint: str

    attempted: bool
    applied: bool
    closed: bool

    shopify_sku: str
    requested_quantity: int


@dataclass(frozen=True)
class CaseResolutionView:
    case_id: str
    shopify_sku: str
    requested_quantity: int

    resolution_code: str
    resolution_fingerprint: str

    status: str

    actor: str
    note: str

    error_message: str | None


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
        raise CaseResolutionError(
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
        raise CaseResolutionError(
            f"{field_name} must be a 64-character SHA-256 hex digest."
        )
