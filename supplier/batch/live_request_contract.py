"""V2.8B/1: offline, fail-closed Shopify batch request contract.

This module ONLY builds a proposed GraphQL request; it never contacts Shopify,
reads/writes SQLite, authorizes an execution, or submits a mutation.

IMPORTANT: The real executor must construct Evidence from a verified, fresh
preflight result (not caller-supplied text) and persist an immutable operation
ID / payload binding before sending anything to Shopify.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID


class ContractRejected(ValueError):
    """The candidate mutation cannot proceed to live integration."""


FINGERPRINT_RE: Final = re.compile(r"^[a-f0-9]{64}$")
INVENTORY_GID_RE: Final = re.compile(r"^gid://shopify/InventoryItem/[1-9][0-9]*$")
LOCATION_GID_RE: Final = re.compile(r"^gid://shopify/Location/[1-9][0-9]*$")
MAX_ITEMS: Final = 2
MAX_ABS_DELTA_PER_ITEM: Final = 2
MAX_TOTAL_ABS_DELTA: Final = 3


INVENTORY_SET_QUANTITIES: Final = """mutation inventorySetQuantities(
  $input: InventorySetQuantitiesInput!,
  $idempotencyKey: String!
) {
  inventorySetQuantities(input: $input) @idempotent(key: $idempotencyKey) {
    inventoryAdjustmentGroup {
      reason
      referenceDocumentUri
      changes {
        name
        delta
        quantityAfterChange
      }
    }
    userErrors {
      code
      field
      message
    }
  }
}"""


@dataclass(frozen=True, slots=True)
class PreflightEvidence:
    """Structural evidence; the live adapter MUST obtain it from trusted code."""

    plan_fingerprint: str
    manifest_fingerprint: str
    approved_manifest_fingerprint: str
    preflight_fingerprint: str
    status: str
    ready_items: int
    stale_items: int
    blocked_items: int


@dataclass(frozen=True, slots=True)
class CandidateQuantity:
    sku: str
    inventory_item_id: str
    location_id: str
    baseline: int
    fresh: int
    proposed: int


@dataclass(frozen=True, slots=True)
class MutationPreview:
    """No network client or execute() method is intentionally provided."""

    operation_id: str
    skus: tuple[str, ...]
    query: str
    variables: dict[str, Any]
    mode: str = "OFFLINE_PREVIEW_ONLY"


def _check_fingerprint(label: str, value: str) -> None:
    if not isinstance(value, str) or FINGERPRINT_RE.fullmatch(value) is None:
        raise ContractRejected(f"{label} must be a 64-character lowercase SHA-256 hex string")


def _check_quantity(label: str, value: int) -> None:
    # bool is a subclass of int in Python, so reject explicitly.
    if type(value) is not int or value < 0:
        raise ContractRejected(f"{label} must be a nonnegative integer (not a bool)")


def _validate(evidence: PreflightEvidence, quantities: tuple[CandidateQuantity, ...]) -> None:
    for label in (
        "plan_fingerprint", "manifest_fingerprint",
        "approved_manifest_fingerprint", "preflight_fingerprint",
    ):
        _check_fingerprint(label, getattr(evidence, label))

    if evidence.manifest_fingerprint != evidence.approved_manifest_fingerprint:
        raise ContractRejected("approved manifest fingerprint does not match candidate manifest")
    if evidence.status != "READY":
        raise ContractRejected("only a freshly READY preflight may produce a mutation preview")
    if (
        evidence.ready_items != MAX_ITEMS
        or evidence.stale_items != 0
        or evidence.blocked_items != 0
    ):
        raise ContractRejected("preflight counts must be exactly 2 ready, 0 stale, 0 blocked")
    if len(quantities) != MAX_ITEMS:
        raise ContractRejected("first live checkpoint is restricted to exactly two items")

    skus: set[str] = set()
    item_ids: set[str] = set()
    location_ids: set[str] = set()
    total_delta = 0

    for quantity in quantities:
        if not isinstance(quantity.sku, str) or not quantity.sku.strip():
            raise ContractRejected("SKU must not be blank")
        if quantity.sku in skus:
            raise ContractRejected("duplicate SKU in batch")
        if not isinstance(quantity.inventory_item_id, str) or not INVENTORY_GID_RE.fullmatch(quantity.inventory_item_id):
            raise ContractRejected(f"invalid inventory item GID for {quantity.sku}")
        if quantity.inventory_item_id in item_ids:
            raise ContractRejected("duplicate inventory item ID in batch")
        if not isinstance(quantity.location_id, str) or not LOCATION_GID_RE.fullmatch(quantity.location_id):
            raise ContractRejected(f"invalid location GID for {quantity.sku}")
        for label in ("baseline", "fresh", "proposed"):
            _check_quantity(f"{quantity.sku}.{label}", getattr(quantity, label))
        if quantity.baseline != quantity.fresh:
            raise ContractRejected(f"STALE: fresh inventory differs from baseline for {quantity.sku}")
        delta = quantity.proposed - quantity.baseline
        if not 1 <= abs(delta) <= MAX_ABS_DELTA_PER_ITEM:
            raise ContractRejected(f"{quantity.sku} delta outside controlled live-test limits")
        total_delta += abs(delta)
        skus.add(quantity.sku)
        item_ids.add(quantity.inventory_item_id)
        location_ids.add(quantity.location_id)

    if len(location_ids) != 1:
        raise ContractRejected("two-item checkpoint requires the exact same Shopify location")
    if total_delta > MAX_TOTAL_ABS_DELTA:
        raise ContractRejected("combined inventory delta exceeds controlled live-test limit")


def prepare_mutation_preview(
    evidence: PreflightEvidence,
    candidates: tuple[CandidateQuantity, ...],
    *,
    operation_id: str,
) -> MutationPreview:
    """Validate a candidate and build Shopify's current GraphQL mutation shape.

    ``operation_id`` must be a NEW persisted UUID for the eventual live attempt.
    Reusing the *same* UUID only makes sense for the *same* immutable payload.
    This function cannot enforce the persistent binding and does not authorize
    or perform any network or database operation.
    """
    if not isinstance(evidence, PreflightEvidence):
        raise ContractRejected("evidence must be PreflightEvidence")
    if not isinstance(candidates, tuple) or not all(isinstance(x, CandidateQuantity) for x in candidates):
        raise ContractRejected("candidates must be a tuple of CandidateQuantity instances")
    try:
        parsed = UUID(operation_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContractRejected("operation_id must be a UUID string") from exc
    if str(parsed) != operation_id or parsed.version != 4:
        raise ContractRejected("operation_id must be a canonical UUIDv4 string")
    _validate(evidence, candidates)

    # Sort so identical candidate sets produce identical payload ordering.
    ordered = tuple(sorted(candidates, key=lambda candidate: candidate.sku))
    variables: dict[str, Any] = {
        "input": {
            "name": "available",
            "reason": "correction",
            "referenceDocumentUri": f"shopify-automation-lab://v2/operations/{operation_id}",
            "quantities": [
                {
                    "inventoryItemId": q.inventory_item_id,
                    "locationId": q.location_id,
                    "quantity": q.proposed,
                    # Mandatory non-null CAS expectation; never opt out.
                    "changeFromQuantity": q.fresh,
                }
                for q in ordered
            ],
        },
        # Shopify 2026-04+ requires @idempotent on this mutation.
        "idempotencyKey": operation_id,
    }
    return MutationPreview(
        operation_id=operation_id,
        skus=tuple(x.sku for x in ordered),
        query=INVENTORY_SET_QUANTITIES,
        variables=variables,
    )
