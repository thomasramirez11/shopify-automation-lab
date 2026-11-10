from dataclasses import replace

from supplier.decision.models import (
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.guard.guard import (
    evaluate_execution_guard,
)
from supplier.guard.models import (
    ExecutionGuardStatus,
)
from supplier.plan.builder import (
    build_dry_run_sync_plan,
)


VARIANT_1 = (
    "gid://shopify/ProductVariant/111"
)

VARIANT_2 = (
    "gid://shopify/ProductVariant/222"
)


def eligible_decision(
    *,
    variant_id=VARIANT_1,
    current=1,
    supplier=25,
    delta=24,
    proposed=25,
):
    return SupplierSyncDecision(
        supplier_code="demo_supplier",
        supplier_sku="SUP-CAP-001",
        shopify_variant_id=variant_id,
        shopify_sku="AUTO-CAP-001",
        status=(
            SyncDecisionStatus.ELIGIBLE
        ),
        reason=(
            SyncDecisionReason
            .INVENTORY_MISMATCH_WITHIN_LIMIT
        ),
        current_inventory_quantity=current,
        supplier_inventory_quantity=supplier,
        inventory_delta=delta,
        proposed_inventory_quantity=(
            proposed
        ),
    )


def test_eligible_plan_without_approval_requires_approval():
    plan = build_dry_run_sync_plan(
        [
            eligible_decision()
        ]
    )

    report = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=None,
    )

    assert (
        report.status
        == ExecutionGuardStatus.APPROVAL_REQUIRED
    )
    assert report.can_execute is False


def test_matching_approval_makes_plan_ready():
    plan = build_dry_run_sync_plan(
        [
            eligible_decision()
        ]
    )

    report = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    assert (
        report.status
        == ExecutionGuardStatus.READY
    )
    assert report.can_execute is True


def test_approval_is_case_insensitive():
    plan = build_dry_run_sync_plan(
        [
            eligible_decision()
        ]
    )

    report = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint.upper()
        ),
    )

    assert report.can_execute is True


def test_changed_plan_invalidates_previous_approval():
    original_plan = (
        build_dry_run_sync_plan(
            [
                eligible_decision()
            ]
        )
    )

    changed_plan = (
        build_dry_run_sync_plan(
            [
                eligible_decision(
                    supplier=26,
                    delta=25,
                    proposed=26,
                )
            ]
        )
    )

    report = evaluate_execution_guard(
        plan=changed_plan,
        approved_fingerprint=(
            original_plan.fingerprint
        ),
    )

    assert (
        report.status
        == ExecutionGuardStatus.FINGERPRINT_MISMATCH
    )
    assert report.can_execute is False


def test_wrong_fingerprint_is_blocked():
    plan = build_dry_run_sync_plan(
        [
            eligible_decision()
        ]
    )

    report = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            "0" * 64
        ),
    )

    assert (
        report.status
        == ExecutionGuardStatus.FINGERPRINT_MISMATCH
    )


def test_blank_approval_is_treated_as_missing():
    plan = build_dry_run_sync_plan(
        [
            eligible_decision()
        ]
    )

    report = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint="   ",
    )

    assert (
        report.status
        == ExecutionGuardStatus.APPROVAL_REQUIRED
    )


def test_malformed_fingerprint_cannot_authorize():
    plan = build_dry_run_sync_plan(
        [
            eligible_decision()
        ]
    )

    report = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint="not-a-sha256",
    )

    assert (
        report.status
        == ExecutionGuardStatus.FINGERPRINT_MISMATCH
    )


def test_review_item_blocks_ready_even_with_matching_fingerprint():
    review = replace(
        eligible_decision(),
        status=SyncDecisionStatus.REVIEW,
        reason=(
            SyncDecisionReason
            .INVENTORY_CHANGE_EXCEEDS_LIMIT
        ),
        proposed_inventory_quantity=None,
    )

    plan = build_dry_run_sync_plan(
        [review]
    )

    report = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    assert (
        report.status
        == ExecutionGuardStatus.REVIEW_REQUIRED
    )
    assert report.can_execute is False


def test_blocked_item_has_highest_priority():
    blocked = replace(
        eligible_decision(),
        status=SyncDecisionStatus.BLOCKED,
        reason=(
            SyncDecisionReason
            .SUPPLIER_PRODUCT_MISSING
        ),
        supplier_inventory_quantity=None,
        inventory_delta=None,
        proposed_inventory_quantity=None,
    )

    plan = build_dry_run_sync_plan(
        [blocked]
    )

    report = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    assert (
        report.status
        == ExecutionGuardStatus.BLOCKED_ITEMS_PRESENT
    )


def test_no_mutations_returns_no_mutations():
    no_action = replace(
        eligible_decision(),
        status=SyncDecisionStatus.NO_ACTION,
        reason=(
            SyncDecisionReason.ALREADY_MATCHED
        ),
        supplier_inventory_quantity=1,
        inventory_delta=0,
        proposed_inventory_quantity=None,
    )

    plan = build_dry_run_sync_plan(
        [no_action]
    )

    report = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    assert (
        report.status
        == ExecutionGuardStatus.NO_MUTATIONS
    )
    assert report.can_execute is False


def test_report_preserves_plan_counts():
    first = eligible_decision()

    second = replace(
        eligible_decision(
            variant_id=VARIANT_2,
            current=2,
            supplier=40,
            delta=38,
            proposed=40,
        ),
        supplier_sku="SUP-SHIRT-L",
        shopify_sku="AUTO-SHIRT-L",
    )

    plan = build_dry_run_sync_plan(
        [
            first,
            second,
        ]
    )

    report = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    assert (
        report.planned_mutations
        == 2
    )
    assert report.review_items == 0
    assert report.blocked_items == 0


def test_current_and_approved_fingerprints_are_reported():
    plan = build_dry_run_sync_plan(
        [
            eligible_decision()
        ]
    )

    report = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    assert (
        report.current_plan_fingerprint
        == plan.fingerprint
    )
    assert (
        report.approved_plan_fingerprint
        == plan.fingerprint
    )
