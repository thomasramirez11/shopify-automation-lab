from dataclasses import replace

import pytest

from supplier.batch.approval import (
    BatchApprovalStatus,
    evaluate_batch_approval,
)
from supplier.batch.builder import (
    build_batch_safety_manifest,
)
from supplier.batch.fake_executor import (
    execute_approved_batch_fake,
)
from supplier.batch.models import (
    BatchSafetyPolicy,
)
from supplier.decision.models import (
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.execution.fake_adapter import (
    FakeInventoryMutationAdapter,
)
from supplier.execution.models import (
    SupplierExecutionError,
)
from supplier.plan.builder import (
    build_dry_run_sync_plan,
)


VARIANT_A = (
    "gid://shopify/ProductVariant/900001"
)

VARIANT_B = (
    "gid://shopify/ProductVariant/900002"
)


def eligible(
    *,
    supplier_sku,
    variant_id,
    shopify_sku,
    current,
    proposed,
):
    return SupplierSyncDecision(
        supplier_code="demo_supplier",
        supplier_sku=supplier_sku,
        shopify_variant_id=variant_id,
        shopify_sku=shopify_sku,
        status=(
            SyncDecisionStatus.ELIGIBLE
        ),
        reason=(
            SyncDecisionReason
            .INVENTORY_MISMATCH_WITHIN_LIMIT
        ),
        current_inventory_quantity=current,
        supplier_inventory_quantity=proposed,
        inventory_delta=(
            proposed - current
        ),
        proposed_inventory_quantity=(
            proposed
        ),
    )


def two_item_plan():
    return build_dry_run_sync_plan(
        [
            eligible(
                supplier_sku="SUP-A",
                variant_id=VARIANT_A,
                shopify_sku="SKU-A",
                current=10,
                proposed=15,
            ),
            eligible(
                supplier_sku="SUP-B",
                variant_id=VARIANT_B,
                shopify_sku="SKU-B",
                current=20,
                proposed=32,
            ),
        ]
    )


def safe_policy():
    return BatchSafetyPolicy(
        max_mutations_per_batch=5,
        max_total_absolute_inventory_delta=100,
        max_single_item_absolute_delta=50,
    )


def ready_manifest():
    plan = two_item_plan()
    manifest = build_batch_safety_manifest(
        plan=plan,
        policy=safe_policy(),
    )
    return plan, manifest


def approved_report(
    plan,
    manifest,
):
    return evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            manifest.manifest_fingerprint
        ),
    )


def test_ready_manifest_requires_approval():
    plan, manifest = ready_manifest()

    report = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=None,
    )

    assert (
        report.status
        == BatchApprovalStatus.APPROVAL_REQUIRED
    )
    assert report.can_execute is False


def test_matching_manifest_approval_is_ready():
    plan, manifest = ready_manifest()

    report = approved_report(
        plan,
        manifest,
    )

    assert (
        report.status
        == BatchApprovalStatus.READY
    )
    assert report.can_execute is True


def test_wrong_manifest_fingerprint_is_rejected():
    plan, manifest = ready_manifest()

    report = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            "f" * 64
        ),
    )

    assert (
        report.status
        == (
            BatchApprovalStatus
            .MANIFEST_FINGERPRINT_MISMATCH
        )
    )


def test_empty_manifest_cannot_be_approved():
    plan = build_dry_run_sync_plan(
        [
            SupplierSyncDecision(
                supplier_code="demo_supplier",
                supplier_sku="SUP-A",
                shopify_variant_id=VARIANT_A,
                shopify_sku="SKU-A",
                status=(
                    SyncDecisionStatus.NO_ACTION
                ),
                reason=(
                    SyncDecisionReason.ALREADY_MATCHED
                ),
                current_inventory_quantity=10,
                supplier_inventory_quantity=10,
                inventory_delta=0,
                proposed_inventory_quantity=None,
            )
        ]
    )

    manifest = build_batch_safety_manifest(
        plan=plan,
        policy=safe_policy(),
    )

    report = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            manifest.manifest_fingerprint
        ),
    )

    assert (
        report.status
        == BatchApprovalStatus.BATCH_NOT_READY
    )


def test_blocked_manifest_cannot_be_approved():
    plan = two_item_plan()

    manifest = build_batch_safety_manifest(
        plan=plan,
        policy=BatchSafetyPolicy(
            max_mutations_per_batch=1,
            max_total_absolute_inventory_delta=100,
            max_single_item_absolute_delta=50,
        ),
    )

    report = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            manifest.manifest_fingerprint
        ),
    )

    assert (
        report.status
        == BatchApprovalStatus.BATCH_NOT_READY
    )


def test_source_plan_mismatch_is_detected():
    plan, manifest = ready_manifest()

    changed_plan = build_dry_run_sync_plan(
        [
            eligible(
                supplier_sku="SUP-A",
                variant_id=VARIANT_A,
                shopify_sku="SKU-A",
                current=10,
                proposed=16,
            ),
            eligible(
                supplier_sku="SUP-B",
                variant_id=VARIANT_B,
                shopify_sku="SKU-B",
                current=20,
                proposed=32,
            ),
        ]
    )

    report = evaluate_batch_approval(
        plan=changed_plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            manifest.manifest_fingerprint
        ),
    )

    assert (
        report.status
        == BatchApprovalStatus.SOURCE_PLAN_MISMATCH
    )


def test_fake_batch_executes_two_mutations():
    plan, manifest = ready_manifest()
    approval = approved_report(
        plan,
        manifest,
    )

    adapter = (
        FakeInventoryMutationAdapter()
    )

    result = execute_approved_batch_fake(
        plan=plan,
        manifest=manifest,
        approval_report=approval,
        inventory_port=adapter,
    )

    assert result.succeeded is True
    assert (
        result.execution_report.attempted_mutations
        == 2
    )
    assert (
        result.execution_report.applied_mutations
        == 2
    )
    assert len(adapter.mutations) == 2


def test_fake_batch_preserves_mutation_order():
    plan, manifest = ready_manifest()
    approval = approved_report(
        plan,
        manifest,
    )

    adapter = (
        FakeInventoryMutationAdapter()
    )

    execute_approved_batch_fake(
        plan=plan,
        manifest=manifest,
        approval_report=approval,
        inventory_port=adapter,
    )

    assert (
        adapter.mutations[0].shopify_sku
        == "SKU-A"
    )
    assert (
        adapter.mutations[1].shopify_sku
        == "SKU-B"
    )


def test_fake_batch_preserves_target_quantities():
    plan, manifest = ready_manifest()
    approval = approved_report(
        plan,
        manifest,
    )

    adapter = (
        FakeInventoryMutationAdapter()
    )

    execute_approved_batch_fake(
        plan=plan,
        manifest=manifest,
        approval_report=approval,
        inventory_port=adapter,
    )

    assert (
        adapter.mutations[0].inventory_quantity
        == 15
    )
    assert (
        adapter.mutations[1].inventory_quantity
        == 32
    )


def test_fake_batch_partial_adapter_failure_is_reported():
    plan, manifest = ready_manifest()
    approval = approved_report(
        plan,
        manifest,
    )

    adapter = FakeInventoryMutationAdapter(
        fail_variant_ids={
            VARIANT_B
        }
    )

    result = execute_approved_batch_fake(
        plan=plan,
        manifest=manifest,
        approval_report=approval,
        inventory_port=adapter,
    )

    assert result.succeeded is False
    assert (
        result.execution_report.attempted_mutations
        == 2
    )
    assert (
        result.execution_report.applied_mutations
        == 1
    )


def test_fake_executor_rejects_unapproved_batch():
    plan, manifest = ready_manifest()

    approval = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=None,
    )

    with pytest.raises(
        SupplierExecutionError,
        match="has not authorized",
    ):
        execute_approved_batch_fake(
            plan=plan,
            manifest=manifest,
            approval_report=approval,
            inventory_port=(
                FakeInventoryMutationAdapter()
            ),
        )


def test_fake_executor_rejects_manifest_from_other_plan():
    plan, manifest = ready_manifest()
    approval = approved_report(
        plan,
        manifest,
    )

    changed_plan = build_dry_run_sync_plan(
        [
            eligible(
                supplier_sku="SUP-A",
                variant_id=VARIANT_A,
                shopify_sku="SKU-A",
                current=10,
                proposed=17,
            ),
            eligible(
                supplier_sku="SUP-B",
                variant_id=VARIANT_B,
                shopify_sku="SKU-B",
                current=20,
                proposed=32,
            ),
        ]
    )

    with pytest.raises(
        SupplierExecutionError,
        match="source plan fingerprint",
    ):
        execute_approved_batch_fake(
            plan=changed_plan,
            manifest=manifest,
            approval_report=approval,
            inventory_port=(
                FakeInventoryMutationAdapter()
            ),
        )


def test_fake_executor_rejects_tampered_approval_report():
    plan, manifest = ready_manifest()
    approval = approved_report(
        plan,
        manifest,
    )

    tampered = replace(
        approval,
        current_manifest_fingerprint=(
            "0" * 64
        ),
    )

    with pytest.raises(
        SupplierExecutionError,
        match="does not match current manifest",
    ):
        execute_approved_batch_fake(
            plan=plan,
            manifest=manifest,
            approval_report=tampered,
            inventory_port=(
                FakeInventoryMutationAdapter()
            ),
        )


def test_manifest_approval_changes_when_policy_changes():
    plan = two_item_plan()

    first = build_batch_safety_manifest(
        plan=plan,
        policy=safe_policy(),
    )

    second = build_batch_safety_manifest(
        plan=plan,
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


def test_old_approval_fails_after_policy_change():
    plan = two_item_plan()

    first = build_batch_safety_manifest(
        plan=plan,
        policy=safe_policy(),
    )

    second = build_batch_safety_manifest(
        plan=plan,
        policy=BatchSafetyPolicy(
            max_mutations_per_batch=4,
            max_total_absolute_inventory_delta=100,
            max_single_item_absolute_delta=50,
        ),
    )

    report = evaluate_batch_approval(
        plan=plan,
        manifest=second,
        approved_manifest_fingerprint=(
            first.manifest_fingerprint
        ),
    )

    assert (
        report.status
        == (
            BatchApprovalStatus
            .MANIFEST_FINGERPRINT_MISMATCH
        )
    )


def test_whitespace_around_approval_is_accepted():
    plan, manifest = ready_manifest()

    report = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            "  "
            + manifest.manifest_fingerprint.upper()
            + "  "
        ),
    )

    assert report.can_execute is True


def test_manifest_fingerprint_not_plan_fingerprint_is_required():
    plan, manifest = ready_manifest()

    report = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            plan.fingerprint
        ),
    )

    assert report.can_execute is False
    assert (
        report.status
        == (
            BatchApprovalStatus
            .MANIFEST_FINGERPRINT_MISMATCH
        )
    )


def test_batch_report_keeps_manifest_identity():
    plan, manifest = ready_manifest()
    approval = approved_report(
        plan,
        manifest,
    )

    result = execute_approved_batch_fake(
        plan=plan,
        manifest=manifest,
        approval_report=approval,
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    assert (
        result.manifest_fingerprint
        == manifest.manifest_fingerprint
    )
    assert (
        result.plan_fingerprint
        == plan.fingerprint
    )


def test_batch_report_keeps_blast_radius():
    plan, manifest = ready_manifest()
    approval = approved_report(
        plan,
        manifest,
    )

    result = execute_approved_batch_fake(
        plan=plan,
        manifest=manifest,
        approval_report=approval,
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    assert result.planned_mutations == 2
    assert (
        result.total_absolute_inventory_delta
        == 17
    )
