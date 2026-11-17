from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SupplierExecutionAuditError(ValueError):
    """Raised when execution-audit data is invalid."""


class SupplierExecutionEventType(str, Enum):
    EXECUTION_STARTED = "execution_started"
    EXECUTION_VERIFIED = "execution_verified"
    EXECUTION_FAILED = "execution_failed"


@dataclass(frozen=True)
class SupplierExecutionAuditEvent:
    operation_id: str
    event_type: SupplierExecutionEventType

    supplier_code: str
    supplier_sku: str

    shopify_variant_id: str
    shopify_sku: str
    inventory_item_id: str
    location_id: str

    before_quantity: int
    requested_quantity: int
    observed_after_quantity: int | None
    inventory_delta: int

    plan_fingerprint: str
    idempotency_key: str
    error_message: str | None = None
    baseline_sync_run_id: int = 0

    def __post_init__(self) -> None:
        _require_text("operation_id", self.operation_id)
        _require_text("supplier_code", self.supplier_code)
        _require_text("supplier_sku", self.supplier_sku)
        _require_gid(
            "shopify_variant_id",
            self.shopify_variant_id,
            "gid://shopify/ProductVariant/",
        )
        _require_text("shopify_sku", self.shopify_sku)
        _require_gid(
            "inventory_item_id",
            self.inventory_item_id,
            "gid://shopify/InventoryItem/",
        )
        _require_gid(
            "location_id",
            self.location_id,
            "gid://shopify/Location/",
        )

        _require_non_negative_integer(
            "before_quantity",
            self.before_quantity,
        )
        _require_non_negative_integer(
            "requested_quantity",
            self.requested_quantity,
        )

        if self.observed_after_quantity is not None:
            _require_non_negative_integer(
                "observed_after_quantity",
                self.observed_after_quantity,
            )

        if (
            isinstance(self.inventory_delta, bool)
            or not isinstance(self.inventory_delta, int)
        ):
            raise SupplierExecutionAuditError(
                "inventory_delta must be an integer."
            )

        fingerprint = self.plan_fingerprint.strip().lower()

        if (
            len(fingerprint) != 64
            or any(
                char not in "0123456789abcdef"
                for char in fingerprint
            )
        ):
            raise SupplierExecutionAuditError(
                "plan_fingerprint must be a 64-character SHA-256 hex digest."
            )

        object.__setattr__(
            self,
            "plan_fingerprint",
            fingerprint,
        )

        _require_text(
            "idempotency_key",
            self.idempotency_key,
        )

        _require_non_negative_integer(
            "baseline_sync_run_id",
            self.baseline_sync_run_id,
        )

        if (
            self.event_type
            == SupplierExecutionEventType.EXECUTION_VERIFIED
            and self.observed_after_quantity is None
        ):
            raise SupplierExecutionAuditError(
                "Verified execution event requires observed_after_quantity."
            )

        if (
            self.event_type
            == SupplierExecutionEventType.EXECUTION_FAILED
            and not (
                isinstance(self.error_message, str)
                and self.error_message.strip()
            )
        ):
            raise SupplierExecutionAuditError(
                "Failed execution event requires error_message."
            )


@dataclass(frozen=True)
class StoredSupplierExecutionAuditEvent:
    event_id: int
    operation_id: str
    event_type: str

    supplier_code: str
    supplier_sku: str

    shopify_variant_id: str
    shopify_sku: str
    inventory_item_id: str
    location_id: str

    before_quantity: int
    requested_quantity: int
    observed_after_quantity: int | None
    inventory_delta: int

    plan_fingerprint: str
    idempotency_key: str
    baseline_sync_run_id: int
    error_message: str | None
    created_at: str


@dataclass(frozen=True)
class AuditAppendResult:
    event_id: int
    created_new: bool


def _require_text(field_name: str, value) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SupplierExecutionAuditError(
            f"{field_name} must be a non-empty string."
        )


def _require_gid(
    field_name: str,
    value,
    prefix: str,
) -> None:
    _require_text(field_name, value)

    if not value.strip().startswith(prefix):
        raise SupplierExecutionAuditError(
            f"{field_name} must start with {prefix}"
        )


def _require_non_negative_integer(
    field_name: str,
    value,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SupplierExecutionAuditError(
            f"{field_name} must be an integer."
        )

    if value < 0:
        raise SupplierExecutionAuditError(
            f"{field_name} cannot be negative."
        )
