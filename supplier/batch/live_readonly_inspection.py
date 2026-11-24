"""V2.8B/6 read-only controller gate and conservative recovery inspection.

These functions never submit mutations or write SQLite. A fresh observation is
not dispatch authorization: all `live_execution_allowed` values are False.
Callers must provide a genuine ShopifyInventoryReadbackAdapter for real reads;
synthetic readback ports are only appropriate for offline tests and demos.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository
from supplier.batch.live_preflight_bridge import PreparedBatchRequest
from supplier.batch.live_recovery_models import RecoveryEventKind
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository
from supplier.batch.live_request_contract import INVENTORY_GID_RE, LOCATION_GID_RE


class ReadOnlyInspectionRejected(ValueError):
    """A candidate or stored operation lacks trustworthy identity evidence."""


class InspectionStatus(str, Enum):
    BASELINES_MATCH = "BASELINES_MATCH"
    STALE = "STALE"
    BLOCKED = "BLOCKED"
    RECOVERY_TARGET_OBSERVED = "RECOVERY_TARGET_OBSERVED"
    RECOVERY_BASELINE_OBSERVED = "RECOVERY_BASELINE_OBSERVED"
    RECOVERY_MIXED_OR_DIVERGED = "RECOVERY_MIXED_OR_DIVERGED"


@dataclass(frozen=True, slots=True)
class InspectionItem:
    sku: str
    baseline: int
    proposed: int
    observed: int
    classification: str


@dataclass(frozen=True, slots=True)
class InspectionReport:
    operation_id: str
    status: InspectionStatus
    items: tuple[InspectionItem, ...]
    successful_reads: int
    dispatch_event_count: int
    human_review_required: bool
    can_continue_to_operator_review: bool
    live_execution_allowed: bool = False
    automatic_retry_allowed: bool = False


def _targets(payload: dict) -> tuple[tuple[str, dict], ...]:
    """Validate the two-item readback request shape before any network I/O."""
    if not isinstance(payload, dict):
        raise ReadOnlyInspectionRejected("missing immutable request payload")
    variables = payload.get("variables")
    if not isinstance(variables, dict) or not isinstance(variables.get("input"), dict):
        raise ReadOnlyInspectionRejected("missing immutable variables")
    quantities = variables["input"].get("quantities")
    skus = payload.get("skus")
    operation_id = payload.get("operation_id")
    if (
        not isinstance(quantities, list) or len(quantities) != 2
        or not isinstance(skus, list) or len(skus) != 2
        or type(operation_id) is not str
        or variables.get("idempotencyKey") != operation_id
    ):
        raise ReadOnlyInspectionRejected("invalid immutable two-item request")
    ids = set()
    names = set()
    location_ids = set()
    for sku, target in zip(skus, quantities):
        if (type(sku) is not str or not sku.strip() or sku in names
                or not isinstance(target, dict)
                or set(target) != {"inventoryItemId", "locationId", "quantity", "changeFromQuantity"}):
            raise ReadOnlyInspectionRejected("invalid or duplicate inventory target")
        inventory_id, location = target["inventoryItemId"], target["locationId"]
        if (type(inventory_id) is not str or INVENTORY_GID_RE.fullmatch(inventory_id) is None
                or inventory_id in ids or type(location) is not str
                or LOCATION_GID_RE.fullmatch(location) is None):
            raise ReadOnlyInspectionRejected("invalid or duplicate inventory identity")
        if any(type(target[k]) is not int or target[k] < 0 for k in ("quantity", "changeFromQuantity")):
            raise ReadOnlyInspectionRejected("invalid baseline or proposed quantity")
        if target["quantity"] == target["changeFromQuantity"]:
            raise ReadOnlyInspectionRejected("zero-delta item in immutable request")
        ids.add(inventory_id)
        names.add(sku)
        location_ids.add(location)
    if len(location_ids) != 1 or payload.get("location_id") not in location_ids:
        raise ReadOnlyInspectionRejected("inventory location identity mismatch")
    return tuple(zip(skus, quantities))


def _inspect(payload: dict, port: Any, *, event_count: int) -> InspectionReport:
    targets = _targets(payload)
    if type(event_count) is not int or event_count < 0:
        raise ReadOnlyInspectionRejected("invalid dispatch event count")
    items: list[InspectionItem] = []
    successes = 0
    for sku, target in targets:
        try:
            state = port.read_available(
                inventory_item_id=target["inventoryItemId"],
                location_id=target["locationId"],
            )
            if (
                state.inventory_item_id != target["inventoryItemId"]
                or state.location_id != target["locationId"]
                or state.sku != sku
                or state.tracked is not True
                or state.level_active is not True
                or state.location_active is not True
                or type(state.available_quantity) is not int
                or state.available_quantity < 0
            ):
                raise ReadOnlyInspectionRejected("Shopify response identity or inventory state invalid")
            successes += 1
            actual = state.available_quantity
            baseline, proposed = target["changeFromQuantity"], target["quantity"]
            classification = (
                "BASELINE" if actual == baseline else
                "TARGET" if actual == proposed else "DIVERGED"
            )
            items.append(InspectionItem(sku, baseline, proposed, actual, classification))
        except Exception:
            # Never log raw Shopify response bodies, network errors, or secrets.
            return InspectionReport(
                operation_id=payload["operation_id"], status=InspectionStatus.BLOCKED,
                items=tuple(items), successful_reads=successes,
                dispatch_event_count=event_count, human_review_required=True,
                can_continue_to_operator_review=False,
            )

    classifications = [i.classification for i in items]
    if event_count:
        # Armed is *always* uncertain even if a fresh quantity matches the target.
        status = (
            InspectionStatus.RECOVERY_TARGET_OBSERVED if classifications == ["TARGET", "TARGET"]
            else InspectionStatus.RECOVERY_BASELINE_OBSERVED if classifications == ["BASELINE", "BASELINE"]
            else InspectionStatus.RECOVERY_MIXED_OR_DIVERGED
        )
        review = False  # Never enter a new execution path from an armed operation.
    else:
        status = InspectionStatus.BASELINES_MATCH if classifications == ["BASELINE", "BASELINE"] else InspectionStatus.STALE
        review = status == InspectionStatus.BASELINES_MATCH
    return InspectionReport(
        operation_id=payload["operation_id"], status=status,
        items=tuple(items), successful_reads=successes,
        dispatch_event_count=event_count, human_review_required=event_count > 0 or not review,
        can_continue_to_operator_review=review,
    )


def inspect_fresh_candidate(prepared: PreparedBatchRequest, *, readback_port: Any) -> InspectionReport:
    """Second independent read of a validated V2.8A preflight (NO DB writes).

    Even BASELINES_MATCH is just an operator-review signal: the request is
    ephemeral, NOT persisted/armed or authorized for Shopify execution.
    """
    SupplierLiveBatchIntentRepository.validate_prepared(prepared)
    payload = SupplierLiveBatchRecoveryRepository._make_payload(prepared)
    return _inspect(payload, readback_port, event_count=0)


def inspect_saved_operation(
    *, archive: ReadOnlyRecoveryArchive, operation_id: str, readback_port: Any,
) -> InspectionReport:
    """Verify persisted SQLite evidence THEN query Shopify without changing DB.

    Loading the saved record and the hash-chained journal from a read-only
    archive is mandatory. Caller-created snapshot or event objects are not
    accepted, so stale/malformed data cannot quietly bypass verification.
    """
    if not isinstance(archive, ReadOnlyRecoveryArchive):
        raise ReadOnlyInspectionRejected("a verified read-only recovery archive is required")
    snapshot, events = archive.load_verified(operation_id)
    if events and events[0].kind != RecoveryEventKind.DISPATCH_ARMED:
        raise ReadOnlyInspectionRejected("missing dispatch-armed event")
    return _inspect(snapshot.payload, readback_port, event_count=len(events))
