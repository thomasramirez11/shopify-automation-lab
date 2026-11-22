"""V2.8B/2: connect trusted preflight to the offline Shopify request contract.

IMPORTANT: This module has no GraphQL mutation caller and no SQLite access.
The injected readback port MUST be a genuine Shopify readback in a later live
controller. Synthetic ports are used only in isolated tests and demos.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import uuid4

from supplier.batch.builder import build_batch_safety_manifest
from supplier.batch.live_request_contract import (
    CandidateQuantity,
    ContractRejected,
    MutationPreview,
    PreflightEvidence,
    prepare_mutation_preview,
)
from supplier.batch.models import BatchSafetyError, BatchSafetyStatus
from supplier.preflight.models import (
    BatchPreflightError,
    BatchPreflightItemStatus,
    BatchPreflightReason,
    BatchPreflightReport,
    BatchPreflightStatus,
)
from supplier.plan.builder import calculate_plan_fingerprint
from supplier.preflight.service import (
    evaluate_live_batch_preflight,
    validate_plan_manifest_identity,
)


@dataclass(frozen=True, slots=True)
class PreparedBatchRequest:
    """Read-only result; it is NOT permission to send a Shopify mutation."""

    batch_id: str
    plan_fingerprint: str
    manifest_fingerprint: str
    preflight_fingerprint: str
    location_id: str
    request_digest: str
    preflight: BatchPreflightReport
    preview: MutationPreview
    mode: str = "OFFLINE_PREVIEW_ONLY"


def calculate_request_digest(
    *, batch_id: str, plan_fingerprint: str, manifest_fingerprint: str,
    preflight_fingerprint: str, location_id: str, preview: MutationPreview,
) -> str:
    """Bind the immutable request contents, CAS values and UUID to the audit identity."""
    payload = {
        "batch_id": batch_id,
        "plan_fingerprint": plan_fingerprint,
        "manifest_fingerprint": manifest_fingerprint,
        "preflight_fingerprint": preflight_fingerprint,
        "location_id": location_id,
        "query": preview.query,
        "variables": preview.variables,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _verify_manifest(plan, manifest) -> None:
    """Rebuild the canonical manifest and fail closed if it was edited."""
    if calculate_plan_fingerprint(plan) != plan.fingerprint:
        raise ContractRejected("source plan fingerprint does not match its contents")
    try:
        validate_plan_manifest_identity(plan=plan, manifest=manifest)
        rebuilt = build_batch_safety_manifest(plan=plan, policy=manifest.policy)
    except (BatchPreflightError, BatchSafetyError) as exc:
        raise ContractRejected("manifest changed or plan/manifest identity invalid") from exc
    if rebuilt != manifest or manifest.status != BatchSafetyStatus.READY:
        raise ContractRejected("manifest changed since build or is not READY")
    if plan.blocked_items or plan.review_items or plan.planned_mutations != 2:
        raise ContractRejected("controlled batch requires exactly two eligible mutations")


def prepare_from_fresh_preflight(
    *, plan, manifest, approval_report, target_resolver, readback_port,
    expected_location_id: str,
) -> PreparedBatchRequest:
    """Make fresh READ calls, validate every target, then build an offline preview.

    No caller-supplied PreflightEvidence or CandidateQuantity is accepted here.
    Operation UUID is generated *after* successful preflight and validation.
    """
    _verify_manifest(plan, manifest)
    if (
        not approval_report.can_execute
        or approval_report.approved_manifest_fingerprint != manifest.manifest_fingerprint
        or approval_report.current_plan_fingerprint != plan.fingerprint
        or approval_report.current_manifest_fingerprint != manifest.manifest_fingerprint
    ):
        raise ContractRejected("human approval is not bound to this manifest and plan")

    report = evaluate_live_batch_preflight(
        plan=plan,
        manifest=manifest,
        approval_report=approval_report,
        target_resolver=target_resolver,
        readback_port=readback_port,
        expected_location_id=expected_location_id,
    )
    if (
        report.status != BatchPreflightStatus.READY
        or not report.can_execute
        or report.reasons != (BatchPreflightReason.READY,)
        or len(report.items) != 2
        or (report.ready_items, report.stale_items, report.blocked_items) != (2, 0, 0)
    ):
        raise ContractRejected(f"fresh batch preflight is not READY: {report.status.value}")
    if (
        report.source_plan_fingerprint != plan.fingerprint
        or report.manifest_fingerprint != manifest.manifest_fingerprint
        or report.approved_manifest_fingerprint != manifest.manifest_fingerprint
        or report.location_id != expected_location_id.strip()
    ):
        raise ContractRejected("fresh preflight identity changed")

    candidates = []
    for index, (mutation, item) in enumerate(zip(manifest.mutations, report.items), start=1):
        if (
            item.item_index != index
            or item.status != BatchPreflightItemStatus.READY
            or item.reasons != (BatchPreflightReason.READY,)
            or item.error_message is not None
            or item.shopify_variant_id != mutation.shopify_variant_id
            or item.supplier_sku != mutation.supplier_sku
            or item.shopify_sku != mutation.shopify_sku
            or item.approved_baseline_quantity != mutation.current_inventory_quantity
            or item.proposed_inventory_quantity != mutation.proposed_inventory_quantity
            or item.inventory_delta != mutation.inventory_delta
            or item.location_id != report.location_id
            or item.fresh_shopify_quantity != item.approved_baseline_quantity
            or item.inventory_item_id is None
        ):
            raise ContractRejected(f"preflight item #{index} does not match the approved mutation")
        candidates.append(CandidateQuantity(
            sku=item.shopify_sku,
            inventory_item_id=item.inventory_item_id,
            location_id=item.location_id,
            baseline=item.approved_baseline_quantity,
            fresh=item.fresh_shopify_quantity,
            proposed=item.proposed_inventory_quantity,
        ))

    evidence = PreflightEvidence(
        plan_fingerprint=report.source_plan_fingerprint,
        manifest_fingerprint=report.manifest_fingerprint,
        approved_manifest_fingerprint=report.approved_manifest_fingerprint,
        preflight_fingerprint=report.preflight_fingerprint,
        status=report.status.value.upper(),
        ready_items=report.ready_items,
        stale_items=report.stale_items,
        blocked_items=report.blocked_items,
    )
    preview = prepare_mutation_preview(
        evidence, tuple(candidates), operation_id=str(uuid4())
    )
    batch_id = hashlib.sha256(
        ("supplier-batch:" + manifest.manifest_fingerprint).encode("utf-8")
    ).hexdigest()  # Same derivation as SupplierBatchExecutionAuditService.build_batch_id.
    digest = calculate_request_digest(
        batch_id=batch_id, plan_fingerprint=plan.fingerprint,
        manifest_fingerprint=manifest.manifest_fingerprint,
        preflight_fingerprint=report.preflight_fingerprint,
        location_id=report.location_id, preview=preview,
    )
    return PreparedBatchRequest(
        batch_id=batch_id,
        plan_fingerprint=plan.fingerprint,
        manifest_fingerprint=manifest.manifest_fingerprint,
        preflight_fingerprint=report.preflight_fingerprint,
        location_id=report.location_id,
        request_digest=digest,
        preflight=report,
        preview=preview,
    )
