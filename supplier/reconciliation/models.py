from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReconciliationStatus(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    VARIANT_MISSING = "variant_missing"


@dataclass(frozen=True)
class VerifiedExecutionCandidate:
    verified_event_id: int
    operation_id: str

    shopify_variant_id: str
    shopify_sku: str

    expected_quantity: int
    baseline_sync_run_id: int

    verified_at: str


@dataclass(frozen=True)
class ReconciliationObservation:
    operation_id: str
    verified_event_id: int
    sync_run_id: int

    shopify_variant_id: str
    shopify_sku: str

    expected_quantity: int
    observed_sqlite_quantity: int | None

    status: ReconciliationStatus


@dataclass(frozen=True)
class StoredReconciliationEvent:
    reconciliation_id: int

    operation_id: str
    verified_event_id: int
    sync_run_id: int

    shopify_variant_id: str
    shopify_sku: str

    expected_quantity: int
    observed_sqlite_quantity: int | None

    status: str
    created_at: str


@dataclass(frozen=True)
class ReconciliationAppendResult:
    reconciliation_id: int
    created_new: bool


@dataclass(frozen=True)
class ReconciliationRunSummary:
    verified_operations_seen: int
    already_matched: int
    waiting_for_new_v1_sync: int
    reconciliations_written: int
    matches_written: int
    mismatches_written: int
    missing_variants_written: int
