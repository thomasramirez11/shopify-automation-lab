from dataclasses import replace

import pytest

from supplier.decision.models import (
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.plan.builder import (
    build_dry_run_sync_plan,
)
from supplier.plan.models import (
    SupplierSyncPlanError,
    SyncPlanAction,
    SyncPlanMode,
)


VARIANT_1 = (
    "gid://shopify/ProductVariant/111"
)

VARIANT_2 = (
    "gid://shopify/ProductVariant/222"
)


def decision(
    *,
    variant_id=VARIANT_1,
    shopify_sku="AUTO-CAP-001",
    status=SyncDecisionStatus.ELIGIBLE,
    reason=(
        SyncDecisionReason
        .INVENTORY_MISMATCH_WITHIN_LIMIT
    ),
    current=1,
    supplier=25,
    delta=24,
    proposed=25,
):
    return SupplierSyncDecision(
        supplier_code="demo_supplier",
        supplier_sku="SUP-CAP-001",
        shopify_variant_id=variant_id,
        shopify_sku=shopify_sku,
        status=status,
        reason=reason,
        current_inventory_quantity=current,
        supplier_inventory_quantity=supplier,
        inventory_delta=delta,
        proposed_inventory_quantity=proposed,
    )


def test_plan_mode_is_dry_run():
    plan = build_dry_run_sync_plan(
        [
            decision()
        ]
    )

    assert (
        plan.mode
        == SyncPlanMode.DRY_RUN
    )


def test_eligible_decision_becomes_inventory_action():
    plan = build_dry_run_sync_plan(
        [
            decision()
        ]
    )

    item = plan.items[0]

    assert (
        item.action
        == SyncPlanAction.SET_INVENTORY
    )
    assert (
        item.proposed_inventory_quantity
        == 25
    )
    assert (
        item.would_mutate_shopify
        is True
    )


def test_review_decision_becomes_no_action():
    review = decision(
        status=SyncDecisionStatus.REVIEW,
        reason=(
            SyncDecisionReason
            .INVENTORY_CHANGE_EXCEEDS_LIMIT
        ),
        proposed=None,
    )

    plan = build_dry_run_sync_plan(
        [review]
    )

    assert (
        plan.items[0].action
        == SyncPlanAction.NONE
    )
    assert (
        plan.planned_mutations
        == 0
    )
    assert (
        plan.review_items
        == 1
    )


def test_blocked_decision_becomes_no_action():
    blocked = decision(
        status=SyncDecisionStatus.BLOCKED,
        reason=(
            SyncDecisionReason
            .SUPPLIER_PRODUCT_MISSING
        ),
        proposed=None,
        supplier=None,
        delta=None,
    )

    plan = build_dry_run_sync_plan(
        [blocked]
    )

    assert (
        plan.items[0].action
        == SyncPlanAction.NONE
    )
    assert (
        plan.blocked_items
        == 1
    )


def test_no_action_decision_becomes_no_action():
    no_action = decision(
        status=SyncDecisionStatus.NO_ACTION,
        reason=(
            SyncDecisionReason
            .ALREADY_MATCHED
        ),
        proposed=None,
        supplier=1,
        delta=0,
    )

    plan = build_dry_run_sync_plan(
        [no_action]
    )

    assert (
        plan.items[0].action
        == SyncPlanAction.NONE
    )
    assert (
        plan.no_action_items
        == 1
    )


def test_mixed_plan_counts_are_correct():
    eligible = decision()

    review = decision(
        variant_id=VARIANT_2,
        shopify_sku="AUTO-SHIRT-L",
        status=SyncDecisionStatus.REVIEW,
        reason=(
            SyncDecisionReason
            .INVENTORY_CHANGE_EXCEEDS_LIMIT
        ),
        proposed=None,
        current=2,
        supplier=100,
        delta=98,
    )

    plan = build_dry_run_sync_plan(
        [
            eligible,
            review,
        ]
    )

    assert len(plan.items) == 2
    assert (
        plan.planned_mutations
        == 1
    )
    assert (
        plan.review_items
        == 1
    )


def test_empty_plan_is_valid():
    plan = build_dry_run_sync_plan(
        []
    )

    assert plan.items == ()
    assert (
        plan.planned_mutations
        == 0
    )
    assert len(
        plan.fingerprint
    ) == 64


def test_fingerprint_is_deterministic():
    first = build_dry_run_sync_plan(
        [
            decision()
        ]
    )

    second = build_dry_run_sync_plan(
        [
            decision()
        ]
    )

    assert (
        first.fingerprint
        == second.fingerprint
    )


def test_inventory_change_changes_fingerprint():
    first = build_dry_run_sync_plan(
        [
            decision(
                proposed=25,
                supplier=25,
                delta=24,
            )
        ]
    )

    second = build_dry_run_sync_plan(
        [
            decision(
                proposed=26,
                supplier=26,
                delta=25,
            )
        ]
    )

    assert (
        first.fingerprint
        != second.fingerprint
    )


def test_decision_status_change_changes_fingerprint():
    eligible = build_dry_run_sync_plan(
        [
            decision()
        ]
    )

    review_decision = decision(
        status=SyncDecisionStatus.REVIEW,
        reason=(
            SyncDecisionReason
            .INVENTORY_CHANGE_EXCEEDS_LIMIT
        ),
        proposed=None,
    )

    review = build_dry_run_sync_plan(
        [
            review_decision
        ]
    )

    assert (
        eligible.fingerprint
        != review.fingerprint
    )


def test_eligible_without_proposed_quantity_is_rejected():
    bad = decision(
        proposed=None
    )

    with pytest.raises(
        SupplierSyncPlanError,
        match="ELIGIBLE decision must include",
    ):
        build_dry_run_sync_plan(
            [bad]
        )


def test_non_eligible_with_proposed_quantity_is_rejected():
    bad = decision(
        status=SyncDecisionStatus.REVIEW,
        reason=(
            SyncDecisionReason
            .COST_CHANGE_REQUIRES_REVIEW
        ),
        proposed=25,
    )

    with pytest.raises(
        SupplierSyncPlanError,
        match="Only ELIGIBLE decisions",
    ):
        build_dry_run_sync_plan(
            [bad]
        )


def test_negative_proposed_quantity_is_rejected():
    bad = decision(
        proposed=-1,
        supplier=-1,
        delta=-2,
    )

    with pytest.raises(
        SupplierSyncPlanError,
        match="cannot be negative",
    ):
        build_dry_run_sync_plan(
            [bad]
        )


def test_duplicate_shopify_target_is_rejected():
    first = decision()

    second = replace(
        decision(),
        supplier_sku="SUP-OTHER",
    )

    with pytest.raises(
        SupplierSyncPlanError,
        match="duplicate Shopify variant target",
    ):
        build_dry_run_sync_plan(
            [
                first,
                second,
            ]
        )


def test_plan_preserves_decision_identity():
    plan = build_dry_run_sync_plan(
        [
            decision()
        ]
    )

    item = plan.items[0]

    assert (
        item.supplier_code
        == "demo_supplier"
    )
    assert (
        item.supplier_sku
        == "SUP-CAP-001"
    )
    assert (
        item.shopify_sku
        == "AUTO-CAP-001"
    )


def test_plan_preserves_inventory_values():
    plan = build_dry_run_sync_plan(
        [
            decision(
                current=2,
                supplier=40,
                delta=38,
                proposed=40,
            )
        ]
    )

    item = plan.items[0]

    assert (
        item.current_inventory_quantity
        == 2
    )
    assert (
        item.proposed_inventory_quantity
        == 40
    )
    assert (
        item.inventory_delta
        == 38
    )


def test_fingerprint_is_sha256_hex():
    plan = build_dry_run_sync_plan(
        [
            decision()
        ]
    )

    assert (
        len(plan.fingerprint)
        == 64
    )

    int(
        plan.fingerprint,
        16,
    )
