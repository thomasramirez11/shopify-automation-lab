from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BatchAuditError(ValueError):
    """Raised when batch audit data is invalid."""


class BatchExecutionEventType(str, Enum):
    BATCH_STARTED = "batch_started"
    BATCH_COMPLETED = "batch_completed"
    BATCH_PARTIAL_FAILURE = "batch_partial_failure"
    BATCH_FAILED = "batch_failed"


class BatchItemEventType(str, Enum):
    ITEM_STARTED = "item_started"
    ITEM_APPLIED = "item_applied"
    ITEM_FAILED = "item_failed"


@dataclass(frozen=True)
class BatchExecutionAuditEvent:
    batch_id: str
    event_type: BatchExecutionEventType

    source_plan_fingerprint: str
    manifest_fingerprint: str

    planned_mutations: int
    total_absolute_inventory_delta: int

    attempted_mutations: int
    applied_mutations: int
    failed_mutations: int

    def __post_init__(self) -> None:
        _require_sha256(
            "batch_id",
            self.batch_id,
        )
        _require_sha256(
            "source_plan_fingerprint",
            self.source_plan_fingerprint,
        )
        _require_sha256(
            "manifest_fingerprint",
            self.manifest_fingerprint,
        )

        for field_name, value in (
            (
                "planned_mutations",
                self.planned_mutations,
            ),
            (
                "total_absolute_inventory_delta",
                self.total_absolute_inventory_delta,
            ),
            (
                "attempted_mutations",
                self.attempted_mutations,
            ),
            (
                "applied_mutations",
                self.applied_mutations,
            ),
            (
                "failed_mutations",
                self.failed_mutations,
            ),
        ):
            _require_non_negative_integer(
                field_name,
                value,
            )

        if (
            self.applied_mutations
            + self.failed_mutations
            > self.attempted_mutations
        ):
            raise BatchAuditError(
                "Applied plus failed mutations cannot exceed attempted mutations."
            )


@dataclass(frozen=True)
class BatchItemAuditEvent:
    batch_id: str
    item_index: int
    operation_id: str

    event_type: BatchItemEventType

    supplier_sku: str
    shopify_variant_id: str
    shopify_sku: str

    before_quantity: int
    requested_quantity: int
    inventory_delta: int

    error_message: str | None = None

    def __post_init__(self) -> None:
        _require_sha256(
            "batch_id",
            self.batch_id,
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
            raise BatchAuditError(
                "item_index must be an integer greater than zero."
            )

        _require_text(
            "supplier_sku",
            self.supplier_sku,
        )

        if not (
            isinstance(
                self.shopify_variant_id,
                str,
            )
            and self.shopify_variant_id.startswith(
                "gid://shopify/ProductVariant/"
            )
        ):
            raise BatchAuditError(
                "shopify_variant_id must be a Shopify ProductVariant GID."
            )

        _require_text(
            "shopify_sku",
            self.shopify_sku,
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
            raise BatchAuditError(
                "inventory_delta must be an integer."
            )

        if (
            self.event_type
            == BatchItemEventType.ITEM_FAILED
            and not (
                isinstance(
                    self.error_message,
                    str,
                )
                and self.error_message.strip()
            )
        ):
            raise BatchAuditError(
                "Failed item event requires error_message."
            )


@dataclass(frozen=True)
class BatchAuditStartResult:
    batch_id: str
    batch_event_id: int
    item_started_event_ids: tuple[int, ...]


@dataclass(frozen=True)
class BatchAuditCompletionResult:
    batch_id: str
    terminal_event_type: BatchExecutionEventType
    terminal_event_id: int
    item_result_event_ids: tuple[int, ...]


@dataclass(frozen=True)
class StoredBatchExecutionEvent:
    event_id: int
    batch_id: str
    event_type: str

    source_plan_fingerprint: str
    manifest_fingerprint: str

    planned_mutations: int
    total_absolute_inventory_delta: int

    attempted_mutations: int
    applied_mutations: int
    failed_mutations: int

    created_at: str


@dataclass(frozen=True)
class StoredBatchItemEvent:
    item_event_id: int
    batch_id: str
    item_index: int
    operation_id: str

    event_type: str

    supplier_sku: str
    shopify_variant_id: str
    shopify_sku: str

    before_quantity: int
    requested_quantity: int
    inventory_delta: int

    error_message: str | None
    created_at: str


@dataclass(frozen=True)
class AuditAppendResult:
    event_id: int
    created_new: bool


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
        raise BatchAuditError(
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
        or len(value.strip()) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character in value.strip().lower()
        )
    ):
        raise BatchAuditError(
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
        raise BatchAuditError(
            f"{field_name} must be an integer."
        )

    if value < 0:
        raise BatchAuditError(
            f"{field_name} cannot be negative."
        )
