from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BatchPreflightError(ValueError):
    """Raised when a live-batch preflight cannot be trusted."""


class BatchPreflightStatus(str, Enum):
    READY = "ready"
    STALE = "stale"
    BLOCKED = "blocked"


class BatchPreflightItemStatus(str, Enum):
    READY = "ready"
    STALE = "stale"
    BLOCKED = "blocked"


class BatchPreflightReason(str, Enum):
    READY = "ready"

    APPROVAL_NOT_READY = "approval_not_ready"
    SOURCE_PLAN_MISMATCH = "source_plan_mismatch"
    MANIFEST_MUTATION_MISMATCH = "manifest_mutation_mismatch"

    TARGET_NOT_RESOLVED = "target_not_resolved"
    TARGET_LOCATION_MISMATCH = "target_location_mismatch"
    LIVE_READ_FAILED = "live_read_failed"

    SKU_MISMATCH = "sku_mismatch"
    INVENTORY_NOT_TRACKED = "inventory_not_tracked"
    LOCATION_INACTIVE = "location_inactive"
    INVENTORY_LEVEL_INACTIVE = "inventory_level_inactive"

    BASELINE_DRIFT = "baseline_drift"


@dataclass(frozen=True)
class BatchPreflightItem:
    item_index: int

    supplier_sku: str
    shopify_variant_id: str
    shopify_sku: str

    inventory_item_id: str | None
    location_id: str

    approved_baseline_quantity: int
    fresh_shopify_quantity: int | None
    proposed_inventory_quantity: int
    inventory_delta: int

    status: BatchPreflightItemStatus
    reasons: tuple[
        BatchPreflightReason,
        ...,
    ]

    error_message: str | None = None


@dataclass(frozen=True)
class BatchPreflightReport:
    status: BatchPreflightStatus
    reasons: tuple[
        BatchPreflightReason,
        ...,
    ]

    source_plan_fingerprint: str
    manifest_fingerprint: str
    approved_manifest_fingerprint: str | None

    location_id: str

    preflight_fingerprint: str

    items: tuple[
        BatchPreflightItem,
        ...,
    ]

    @property
    def can_execute(self) -> bool:
        return (
            self.status
            == BatchPreflightStatus.READY
        )

    @property
    def ready_items(self) -> int:
        return sum(
            1
            for item in self.items
            if (
                item.status
                == BatchPreflightItemStatus.READY
            )
        )

    @property
    def stale_items(self) -> int:
        return sum(
            1
            for item in self.items
            if (
                item.status
                == BatchPreflightItemStatus.STALE
            )
        )

    @property
    def blocked_items(self) -> int:
        return sum(
            1
            for item in self.items
            if (
                item.status
                == BatchPreflightItemStatus.BLOCKED
            )
        )
