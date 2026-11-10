from dataclasses import replace

import pytest

from supplier.decision.models import (
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.execution.executor import (
    execute_sync_plan,
)
from supplier.execution.fake_adapter import (
    FakeInventoryMutationAdapter,
)
from supplier.execution.models import (
    InventoryMutation,
    SupplierExecutionError,
)
from supplier.guard.guard import (
    evaluate_execution_guard,
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
    supplier_sku="SUP-CAP-001",
    shopify_sku="AUTO-CAP-001",
    current=1,
    supplier=25,
    delta=24,
    proposed=25,
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
        supplier_inventory_quantity=supplier,
        inventory_delta=delta,
        proposed_inventory_quantity=(
            proposed
        ),
    )


def approved_plan(
    decisions=None,
):
    plan = build_dry_run_sync_plan(
        decisions
        or [
            eligible_decision()
        ]
    )

    guard = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    return plan, guard


def test_fake_adapter_records_mutation():
    adapter = (
        FakeInventoryMutationAdapter()
    )

    mutation = InventoryMutation(
        shopify_variant_id=(
            VARIANT_1
        ),
        shopify_sku="AUTO-CAP-001",
        inventory_quantity=25,
    )

    result = adapter.set_inventory(
        mutation
    )

    assert adapter.mutations == (
        mutation,
    )
    assert result.applied is True


def test_executor_applies_one_approved_inventory_mutation():
    plan, guard = approved_plan()

    adapter = (
        FakeInventoryMutationAdapter()
    )

    report = execute_sync_plan(
        plan=plan,
        guard_report=guard,
        inventory_port=adapter,
    )

    assert (
        report.attempted_mutations
        == 1
    )
    assert (
        report.applied_mutations
        == 1
    )
    assert report.succeeded is True

    assert (
        adapter.mutations[0]
        .inventory_quantity
        == 25
    )


def test_executor_applies_multiple_inventory_mutations():
    decisions = [
        eligible_decision(),
        eligible_decision(
            variant_id=VARIANT_2,
            supplier_sku="SUP-SHIRT-L",
            shopify_sku="AUTO-SHIRT-L",
            current=2,
            supplier=40,
            delta=38,
            proposed=40,
        ),
    ]

    plan, guard = approved_plan(
        decisions
    )

    adapter = (
        FakeInventoryMutationAdapter()
    )

    report = execute_sync_plan(
        plan=plan,
        guard_report=guard,
        inventory_port=adapter,
    )

    assert (
        report.attempted_mutations
        == 2
    )
    assert (
        report.applied_mutations
        == 2
    )
    assert len(
        adapter.mutations
    ) == 2


def test_executor_rejects_unapproved_plan():
    plan = build_dry_run_sync_plan(
        [
            eligible_decision()
        ]
    )

    guard = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=None,
    )

    adapter = (
        FakeInventoryMutationAdapter()
    )

    with pytest.raises(
        SupplierExecutionError,
        match="has not authorized",
    ):
        execute_sync_plan(
            plan=plan,
            guard_report=guard,
            inventory_port=adapter,
        )

    assert adapter.mutations == ()


def test_executor_rejects_guard_for_different_plan():
    first_plan, first_guard = (
        approved_plan()
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

    adapter = (
        FakeInventoryMutationAdapter()
    )

    with pytest.raises(
        SupplierExecutionError,
        match="fingerprint does not match",
    ):
        execute_sync_plan(
            plan=changed_plan,
            guard_report=(
                first_guard
            ),
            inventory_port=adapter,
        )

    assert adapter.mutations == ()


def test_review_item_produces_zero_mutations():
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

    guard = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    adapter = (
        FakeInventoryMutationAdapter()
    )

    with pytest.raises(
        SupplierExecutionError,
        match="has not authorized",
    ):
        execute_sync_plan(
            plan=plan,
            guard_report=guard,
            inventory_port=adapter,
        )

    assert adapter.mutations == ()


def test_blocked_item_produces_zero_mutations():
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

    guard = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    adapter = (
        FakeInventoryMutationAdapter()
    )

    with pytest.raises(
        SupplierExecutionError,
        match="has not authorized",
    ):
        execute_sync_plan(
            plan=plan,
            guard_report=guard,
            inventory_port=adapter,
        )

    assert adapter.mutations == ()


def test_no_action_plan_produces_zero_mutations():
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

    guard = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    adapter = (
        FakeInventoryMutationAdapter()
    )

    with pytest.raises(
        SupplierExecutionError,
        match="has not authorized",
    ):
        execute_sync_plan(
            plan=plan,
            guard_report=guard,
            inventory_port=adapter,
        )

    assert adapter.mutations == ()


def test_fake_adapter_can_simulate_failed_mutation():
    plan, guard = approved_plan()

    adapter = (
        FakeInventoryMutationAdapter(
            fail_variant_ids={
                VARIANT_1
            }
        )
    )

    report = execute_sync_plan(
        plan=plan,
        guard_report=guard,
        inventory_port=adapter,
    )

    assert (
        report.attempted_mutations
        == 1
    )
    assert (
        report.applied_mutations
        == 0
    )
    assert report.succeeded is False


def test_mixed_fake_results_are_reported():
    decisions = [
        eligible_decision(),
        eligible_decision(
            variant_id=VARIANT_2,
            supplier_sku="SUP-SHIRT-L",
            shopify_sku="AUTO-SHIRT-L",
            current=2,
            supplier=40,
            delta=38,
            proposed=40,
        ),
    ]

    plan, guard = approved_plan(
        decisions
    )

    adapter = (
        FakeInventoryMutationAdapter(
            fail_variant_ids={
                VARIANT_2
            }
        )
    )

    report = execute_sync_plan(
        plan=plan,
        guard_report=guard,
        inventory_port=adapter,
    )

    assert (
        report.attempted_mutations
        == 2
    )
    assert (
        report.applied_mutations
        == 1
    )
    assert report.succeeded is False


def test_inventory_mutation_rejects_negative_quantity():
    with pytest.raises(
        SupplierExecutionError,
        match="cannot be negative",
    ):
        InventoryMutation(
            shopify_variant_id=(
                VARIANT_1
            ),
            shopify_sku=(
                "AUTO-CAP-001"
            ),
            inventory_quantity=-1,
        )


def test_inventory_mutation_rejects_non_integer_quantity():
    with pytest.raises(
        SupplierExecutionError,
        match="must be an integer",
    ):
        InventoryMutation(
            shopify_variant_id=(
                VARIANT_1
            ),
            shopify_sku=(
                "AUTO-CAP-001"
            ),
            inventory_quantity=2.5,
        )


def test_inventory_mutation_rejects_empty_sku():
    with pytest.raises(
        SupplierExecutionError,
        match="shopify_sku cannot be empty",
    ):
        InventoryMutation(
            shopify_variant_id=(
                VARIANT_1
            ),
            shopify_sku="   ",
            inventory_quantity=25,
        )


def test_inventory_mutation_rejects_non_variant_gid():
    with pytest.raises(
        SupplierExecutionError,
        match="ProductVariant GID",
    ):
        InventoryMutation(
            shopify_variant_id=(
                "gid://shopify/Product/123"
            ),
            shopify_sku=(
                "AUTO-CAP-001"
            ),
            inventory_quantity=25,
        )


def test_execution_report_preserves_plan_fingerprint():
    plan, guard = approved_plan()

    adapter = (
        FakeInventoryMutationAdapter()
    )

    report = execute_sync_plan(
        plan=plan,
        guard_report=guard,
        inventory_port=adapter,
    )

    assert (
        report.plan_fingerprint
        == plan.fingerprint
    )


def test_fake_adapter_performs_no_external_io_contract():
    adapter = (
        FakeInventoryMutationAdapter()
    )

    assert adapter.mutations == ()

    plan, guard = approved_plan()

    execute_sync_plan(
        plan=plan,
        guard_report=guard,
        inventory_port=adapter,
    )

    # The only observable side effect is the in-memory mutation log.
    assert len(
        adapter.mutations
    ) == 1
