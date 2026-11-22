from __future__ import annotations

import hashlib
import json

from supplier.batch.models import (
    BatchMutationPreview,
    BatchSafetyError,
    BatchSafetyManifest,
    BatchSafetyPolicy,
    BatchSafetyReason,
    BatchSafetyStatus,
)
from supplier.plan.models import (
    SupplierSyncPlan,
    SyncPlanAction,
)


def build_batch_safety_manifest(
    *,
    plan: SupplierSyncPlan,
    policy: BatchSafetyPolicy,
) -> BatchSafetyManifest:
    """
    Convert a normal dry-run sync plan into a batch-level safety manifest.

    This function performs no Shopify calls and no SQLite writes.
    """

    mutations = tuple(
        _build_mutation_preview(
            item
        )
        for item in plan.items
        if (
            item.action
            == SyncPlanAction.SET_INVENTORY
        )
    )

    total_absolute_delta = sum(
        item.absolute_inventory_delta
        for item in mutations
    )

    largest_single_delta = max(
        (
            item.absolute_inventory_delta
            for item in mutations
        ),
        default=0,
    )

    status, reasons = _evaluate_status(
        plan=plan,
        policy=policy,
        mutations=mutations,
        total_absolute_delta=(
            total_absolute_delta
        ),
        largest_single_delta=(
            largest_single_delta
        ),
    )

    manifest_fingerprint = (
        _build_manifest_fingerprint(
            plan=plan,
            policy=policy,
            mutations=mutations,
            status=status,
            reasons=reasons,
        )
    )

    return BatchSafetyManifest(
        source_plan_fingerprint=(
            plan.fingerprint
        ),
        manifest_fingerprint=(
            manifest_fingerprint
        ),
        status=status,
        reasons=reasons,
        mutations=mutations,
        planned_mutations=(
            plan.planned_mutations
        ),
        review_items=(
            plan.review_items
        ),
        blocked_items=(
            plan.blocked_items
        ),
        no_action_items=(
            plan.no_action_items
        ),
        total_absolute_inventory_delta=(
            total_absolute_delta
        ),
        largest_single_item_absolute_delta=(
            largest_single_delta
        ),
        policy=policy,
    )



def _build_mutation_preview(
    item,
) -> BatchMutationPreview:
    """
    Fail closed for malformed mutation candidates.

    Before V2.8A, a SET_INVENTORY item with a missing current/proposed/delta
    value could be omitted from the batch manifest. That is safe enough for a
    preview, but not acceptable before live multi-item execution.
    """

    required_integer_fields = {
        "current_inventory_quantity":
            item.current_inventory_quantity,
        "proposed_inventory_quantity":
            item.proposed_inventory_quantity,
        "inventory_delta":
            item.inventory_delta,
    }

    for field_name, value in required_integer_fields.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
        ):
            raise BatchSafetyError(
                "SET_INVENTORY plan item "
                f"{item.shopify_variant_id!r} has invalid "
                f"{field_name}; live-batch planning fails closed."
            )

    expected_delta = (
        item.proposed_inventory_quantity
        - item.current_inventory_quantity
    )

    if item.inventory_delta != expected_delta:
        raise BatchSafetyError(
            "SET_INVENTORY plan item "
            f"{item.shopify_variant_id!r} has inconsistent "
            "inventory_delta."
        )

    if item.inventory_delta == 0:
        raise BatchSafetyError(
            "SET_INVENTORY plan item "
            f"{item.shopify_variant_id!r} has zero inventory_delta."
        )

    return BatchMutationPreview(
        supplier_sku=(
            item.supplier_sku
        ),
        shopify_variant_id=(
            item.shopify_variant_id
        ),
        shopify_sku=(
            item.shopify_sku
        ),
        current_inventory_quantity=(
            item.current_inventory_quantity
        ),
        proposed_inventory_quantity=(
            item.proposed_inventory_quantity
        ),
        inventory_delta=(
            item.inventory_delta
        ),
    )

def _evaluate_status(
    *,
    plan: SupplierSyncPlan,
    policy: BatchSafetyPolicy,
    mutations: tuple[
        BatchMutationPreview,
        ...,
    ],
    total_absolute_delta: int,
    largest_single_delta: int,
) -> tuple[
    BatchSafetyStatus,
    tuple[BatchSafetyReason, ...],
]:
    reasons = []

    if plan.blocked_items > 0:
        reasons.append(
            BatchSafetyReason
            .PLAN_HAS_BLOCKED_ITEMS
        )

    if plan.review_items > 0:
        reasons.append(
            BatchSafetyReason
            .PLAN_HAS_REVIEW_ITEMS
        )

    if (
        len(mutations)
        > policy.max_mutations_per_batch
    ):
        reasons.append(
            BatchSafetyReason
            .TOO_MANY_MUTATIONS
        )

    if (
        total_absolute_delta
        > policy
        .max_total_absolute_inventory_delta
    ):
        reasons.append(
            BatchSafetyReason
            .TOTAL_INVENTORY_DELTA_EXCEEDED
        )

    if (
        largest_single_delta
        > policy
        .max_single_item_absolute_delta
    ):
        reasons.append(
            BatchSafetyReason
            .SINGLE_ITEM_DELTA_EXCEEDED
        )

    blocking_reasons = {
        BatchSafetyReason.PLAN_HAS_BLOCKED_ITEMS,
        BatchSafetyReason.TOO_MANY_MUTATIONS,
        BatchSafetyReason.SINGLE_ITEM_DELTA_EXCEEDED,
    }

    if any(
        reason in blocking_reasons
        for reason in reasons
    ):
        return (
            BatchSafetyStatus.BLOCKED,
            tuple(reasons),
        )

    review_reasons = {
        BatchSafetyReason.PLAN_HAS_REVIEW_ITEMS,
        BatchSafetyReason.TOTAL_INVENTORY_DELTA_EXCEEDED,
    }

    if any(
        reason in review_reasons
        for reason in reasons
    ):
        return (
            BatchSafetyStatus.REVIEW_REQUIRED,
            tuple(reasons),
        )

    if not mutations:
        return (
            BatchSafetyStatus.EMPTY,
            (
                BatchSafetyReason
                .NO_MUTATIONS,
            ),
        )

    return (
        BatchSafetyStatus.READY,
        (
            BatchSafetyReason
            .WITHIN_BUDGET,
        ),
    )


def _build_manifest_fingerprint(
    *,
    plan: SupplierSyncPlan,
    policy: BatchSafetyPolicy,
    mutations: tuple[
        BatchMutationPreview,
        ...,
    ],
    status: BatchSafetyStatus,
    reasons: tuple[
        BatchSafetyReason,
        ...,
    ],
) -> str:
    payload = {
        "source_plan_fingerprint":
            plan.fingerprint,
        "policy": {
            "max_mutations_per_batch":
                policy.max_mutations_per_batch,
            "max_total_absolute_inventory_delta":
                policy.max_total_absolute_inventory_delta,
            "max_single_item_absolute_delta":
                policy.max_single_item_absolute_delta,
        },
        "status":
            status.value,
        "reasons": [
            reason.value
            for reason in reasons
        ],
        "mutations": [
            {
                "supplier_sku":
                    item.supplier_sku,
                "shopify_variant_id":
                    item.shopify_variant_id,
                "shopify_sku":
                    item.shopify_sku,
                "current_inventory_quantity":
                    item.current_inventory_quantity,
                "proposed_inventory_quantity":
                    item.proposed_inventory_quantity,
                "inventory_delta":
                    item.inventory_delta,
            }
            for item in mutations
        ],
    }

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()
