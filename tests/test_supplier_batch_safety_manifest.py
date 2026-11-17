from dataclasses import replace

import pytest

from supplier.batch.builder import (
    build_batch_safety_manifest,
)
from supplier.batch.models import (
    BatchSafetyError,
    BatchSafetyPolicy,
    BatchSafetyReason,
    BatchSafetyStatus,
)
from supplier.decision.models import (
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.plan.builder import (
    build_dry_run_sync_plan,
)


def decision(
    *,
    supplier_sku,
    variant_id,
    shopify_sku,
    current,
    supplier,
    status=SyncDecisionStatus.ELIGIBLE,
    reason=(
        SyncDecisionReason
        .INVENTORY_MISMATCH_WITHIN_LIMIT
    ),
):
    delta = (
        supplier - current
        if current is not None
        and supplier is not None
        else None
    )

    proposed = (
        supplier
        if status
        == SyncDecisionStatus.ELIGIBLE
        else None
    )

    return SupplierSyncDecision(
        supplier_code="demo_supplier",
        supplier_sku=supplier_sku,
        shopify_variant_id=variant_id,
        shopify_sku=shopify_sku,
        status=status,
        reason=reason,
        current_inventory_quantity=current,
        supplier_inventory_quantity=supplier,
        inventory_delta=delta,
        proposed_inventory_quantity=proposed,
    )


def ready_plan():
    return build_dry_run_sync_plan(
        [
            decision(
                supplier_sku="SUP-A",
                variant_id="gid://shopify/ProductVariant/1",
                shopify_sku="SKU-A",
                current=2,
                supplier=10,
            ),
            decision(
                supplier_sku="SUP-B",
                variant_id="gid://shopify/ProductVariant/2",
                shopify_sku="SKU-B",
                current=5,
                supplier=12,
            ),
        ]
    )


def default_policy():
    return BatchSafetyPolicy(
        max_mutations_per_batch=5,
        max_total_absolute_inventory_delta=100,
        max_single_item_absolute_delta=50,
    )


def test_ready_batch_within_budget():
    manifest = (
        build_batch_safety_manifest(
            plan=ready_plan(),
            policy=default_policy(),
        )
    )

    assert (
        manifest.status
        == BatchSafetyStatus.READY
    )
    assert manifest.is_ready is True
    assert manifest.planned_mutations == 2
    assert (
        manifest.total_absolute_inventory_delta
        == 15
    )
    assert (
        manifest.largest_single_item_absolute_delta
        == 8
    )


def test_empty_plan_is_safe_empty():
    plan = build_dry_run_sync_plan(
        [
            decision(
                supplier_sku="SUP-A",
                variant_id="gid://shopify/ProductVariant/1",
                shopify_sku="SKU-A",
                current=10,
                supplier=10,
                status=SyncDecisionStatus.NO_ACTION,
                reason=(
                    SyncDecisionReason
                    .ALREADY_MATCHED
                ),
            )
        ]
    )

    manifest = (
        build_batch_safety_manifest(
            plan=plan,
            policy=default_policy(),
        )
    )

    assert (
        manifest.status
        == BatchSafetyStatus.EMPTY
    )
    assert manifest.is_empty is True
    assert (
        manifest.reasons
        == (
            BatchSafetyReason.NO_MUTATIONS,
        )
    )


def test_review_item_requires_batch_review():
    plan = build_dry_run_sync_plan(
        [
            decision(
                supplier_sku="SUP-A",
                variant_id="gid://shopify/ProductVariant/1",
                shopify_sku="SKU-A",
                current=1,
                supplier=80,
                status=SyncDecisionStatus.REVIEW,
                reason=(
                    SyncDecisionReason
                    .INVENTORY_CHANGE_EXCEEDS_LIMIT
                ),
            )
        ]
    )

    manifest = (
        build_batch_safety_manifest(
            plan=plan,
            policy=default_policy(),
        )
    )

    assert (
        manifest.status
        == BatchSafetyStatus.REVIEW_REQUIRED
    )
    assert (
        BatchSafetyReason.PLAN_HAS_REVIEW_ITEMS
        in manifest.reasons
    )


def test_blocked_item_blocks_batch():
    plan = build_dry_run_sync_plan(
        [
            decision(
                supplier_sku="SUP-A",
                variant_id="gid://shopify/ProductVariant/1",
                shopify_sku="SKU-A",
                current=None,
                supplier=10,
                status=SyncDecisionStatus.BLOCKED,
                reason=(
                    SyncDecisionReason
                    .SHOPIFY_VARIANT_MISSING
                ),
            )
        ]
    )

    manifest = (
        build_batch_safety_manifest(
            plan=plan,
            policy=default_policy(),
        )
    )

    assert (
        manifest.status
        == BatchSafetyStatus.BLOCKED
    )
    assert (
        BatchSafetyReason.PLAN_HAS_BLOCKED_ITEMS
        in manifest.reasons
    )


def test_too_many_mutations_blocks_batch():
    plan = ready_plan()

    manifest = (
        build_batch_safety_manifest(
            plan=plan,
            policy=BatchSafetyPolicy(
                max_mutations_per_batch=1,
                max_total_absolute_inventory_delta=100,
                max_single_item_absolute_delta=50,
            ),
        )
    )

    assert (
        manifest.status
        == BatchSafetyStatus.BLOCKED
    )
    assert (
        BatchSafetyReason.TOO_MANY_MUTATIONS
        in manifest.reasons
    )


def test_total_delta_over_budget_requires_review():
    plan = ready_plan()

    manifest = (
        build_batch_safety_manifest(
            plan=plan,
            policy=BatchSafetyPolicy(
                max_mutations_per_batch=5,
                max_total_absolute_inventory_delta=10,
                max_single_item_absolute_delta=50,
            ),
        )
    )

    assert (
        manifest.status
        == BatchSafetyStatus.REVIEW_REQUIRED
    )
    assert (
        BatchSafetyReason
        .TOTAL_INVENTORY_DELTA_EXCEEDED
        in manifest.reasons
    )


def test_single_item_delta_over_budget_blocks():
    plan = build_dry_run_sync_plan(
        [
            decision(
                supplier_sku="SUP-A",
                variant_id="gid://shopify/ProductVariant/1",
                shopify_sku="SKU-A",
                current=1,
                supplier=60,
            )
        ]
    )

    manifest = (
        build_batch_safety_manifest(
            plan=plan,
            policy=BatchSafetyPolicy(
                max_mutations_per_batch=5,
                max_total_absolute_inventory_delta=100,
                max_single_item_absolute_delta=50,
            ),
        )
    )

    assert (
        manifest.status
        == BatchSafetyStatus.BLOCKED
    )
    assert (
        BatchSafetyReason
        .SINGLE_ITEM_DELTA_EXCEEDED
        in manifest.reasons
    )


def test_negative_inventory_delta_counts_as_absolute():
    plan = build_dry_run_sync_plan(
        [
            decision(
                supplier_sku="SUP-A",
                variant_id="gid://shopify/ProductVariant/1",
                shopify_sku="SKU-A",
                current=20,
                supplier=5,
            )
        ]
    )

    manifest = (
        build_batch_safety_manifest(
            plan=plan,
            policy=default_policy(),
        )
    )

    assert (
        manifest.total_absolute_inventory_delta
        == 15
    )
    assert (
        manifest.largest_single_item_absolute_delta
        == 15
    )


def test_manifest_fingerprint_is_deterministic():
    first = build_batch_safety_manifest(
        plan=ready_plan(),
        policy=default_policy(),
    )

    second = build_batch_safety_manifest(
        plan=ready_plan(),
        policy=default_policy(),
    )

    assert (
        first.manifest_fingerprint
        == second.manifest_fingerprint
    )


def test_manifest_fingerprint_changes_with_policy():
    first = build_batch_safety_manifest(
        plan=ready_plan(),
        policy=default_policy(),
    )

    second = build_batch_safety_manifest(
        plan=ready_plan(),
        policy=BatchSafetyPolicy(
            max_mutations_per_batch=4,
            max_total_absolute_inventory_delta=100,
            max_single_item_absolute_delta=50,
        ),
    )

    assert (
        first.manifest_fingerprint
        != second.manifest_fingerprint
    )


def test_manifest_fingerprint_changes_with_plan():
    first = build_batch_safety_manifest(
        plan=ready_plan(),
        policy=default_policy(),
    )

    changed_plan = build_dry_run_sync_plan(
        [
            decision(
                supplier_sku="SUP-A",
                variant_id="gid://shopify/ProductVariant/1",
                shopify_sku="SKU-A",
                current=2,
                supplier=11,
            ),
            decision(
                supplier_sku="SUP-B",
                variant_id="gid://shopify/ProductVariant/2",
                shopify_sku="SKU-B",
                current=5,
                supplier=12,
            ),
        ]
    )

    second = build_batch_safety_manifest(
        plan=changed_plan,
        policy=default_policy(),
    )

    assert (
        first.manifest_fingerprint
        != second.manifest_fingerprint
    )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {
                "max_mutations_per_batch": 0,
                "max_total_absolute_inventory_delta": 100,
                "max_single_item_absolute_delta": 50,
            },
            "greater than zero",
        ),
        (
            {
                "max_mutations_per_batch": -1,
                "max_total_absolute_inventory_delta": 100,
                "max_single_item_absolute_delta": 50,
            },
            "cannot be negative",
        ),
        (
            {
                "max_mutations_per_batch": 5,
                "max_total_absolute_inventory_delta": -1,
                "max_single_item_absolute_delta": 50,
            },
            "cannot be negative",
        ),
        (
            {
                "max_mutations_per_batch": 5,
                "max_total_absolute_inventory_delta": 100,
                "max_single_item_absolute_delta": -1,
            },
            "cannot be negative",
        ),
    ],
)
def test_invalid_policy_is_rejected(
    kwargs,
    message,
):
    with pytest.raises(
        BatchSafetyError,
        match=message,
    ):
        BatchSafetyPolicy(
            **kwargs
        )


def test_boolean_policy_value_is_rejected():
    with pytest.raises(
        BatchSafetyError,
        match="integer",
    ):
        BatchSafetyPolicy(
            max_mutations_per_batch=True,
            max_total_absolute_inventory_delta=100,
            max_single_item_absolute_delta=50,
        )


def test_manifest_copies_plan_counts():
    plan = build_dry_run_sync_plan(
        [
            decision(
                supplier_sku="SUP-A",
                variant_id="gid://shopify/ProductVariant/1",
                shopify_sku="SKU-A",
                current=10,
                supplier=15,
            ),
            decision(
                supplier_sku="SUP-B",
                variant_id="gid://shopify/ProductVariant/2",
                shopify_sku="SKU-B",
                current=5,
                supplier=5,
                status=SyncDecisionStatus.NO_ACTION,
                reason=(
                    SyncDecisionReason
                    .ALREADY_MATCHED
                ),
            ),
        ]
    )

    manifest = build_batch_safety_manifest(
        plan=plan,
        policy=default_policy(),
    )

    assert manifest.planned_mutations == 1
    assert manifest.no_action_items == 1


def test_mutation_preview_preserves_quantities():
    manifest = build_batch_safety_manifest(
        plan=ready_plan(),
        policy=default_policy(),
    )

    first = manifest.mutations[0]

    assert (
        first.current_inventory_quantity
        == 2
    )
    assert (
        first.proposed_inventory_quantity
        == 10
    )
    assert first.inventory_delta == 8


def test_ready_reason_is_within_budget():
    manifest = build_batch_safety_manifest(
        plan=ready_plan(),
        policy=default_policy(),
    )

    assert manifest.reasons == (
        BatchSafetyReason.WITHIN_BUDGET,
    )


def test_source_plan_fingerprint_is_preserved():
    plan = ready_plan()

    manifest = build_batch_safety_manifest(
        plan=plan,
        policy=default_policy(),
    )

    assert (
        manifest.source_plan_fingerprint
        == plan.fingerprint
    )
