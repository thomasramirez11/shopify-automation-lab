from dataclasses import replace

import pytest

from supplier.batch.approval import (
    evaluate_batch_approval,
)
from supplier.batch.builder import (
    build_batch_safety_manifest,
)
from supplier.batch.models import (
    BatchSafetyError,
    BatchSafetyPolicy,
)
from supplier.decision.models import (
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.execution.models import (
    SupplierExecutionError,
)
from supplier.execution.readback import (
    InventoryReadbackState,
)
from supplier.execution.shopify_adapter import (
    ShopifyInventoryTarget,
)
from supplier.plan.builder import (
    build_dry_run_sync_plan,
)
from supplier.plan.models import (
    SyncPlanAction,
)
from supplier.preflight.models import (
    BatchPreflightError,
    BatchPreflightItemStatus,
    BatchPreflightReason,
    BatchPreflightStatus,
)
from supplier.preflight.service import (
    evaluate_live_batch_preflight,
    validate_plan_manifest_identity,
)


LOCATION_ID = "gid://shopify/Location/999001"


def build_decision(
    *,
    suffix,
    current,
    proposed,
):
    return SupplierSyncDecision(
        supplier_code="demo_supplier",
        supplier_sku=f"SUP-{suffix}",
        shopify_variant_id=(
            "gid://shopify/ProductVariant/"
            + suffix
        ),
        shopify_sku=f"SKU-{suffix}",
        status=SyncDecisionStatus.ELIGIBLE,
        reason=(
            SyncDecisionReason
            .INVENTORY_MISMATCH_WITHIN_LIMIT
        ),
        current_inventory_quantity=current,
        supplier_inventory_quantity=proposed,
        inventory_delta=(
            proposed - current
        ),
        proposed_inventory_quantity=proposed,
    )


def build_plan():
    return build_dry_run_sync_plan(
        [
            build_decision(
                suffix="1001",
                current=10,
                proposed=15,
            ),
            build_decision(
                suffix="1002",
                current=20,
                proposed=25,
            ),
        ]
    )


def build_manifest_and_approval(
    plan=None,
):
    plan = plan or build_plan()

    manifest = build_batch_safety_manifest(
        plan=plan,
        policy=BatchSafetyPolicy(),
    )

    approval = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            manifest.manifest_fingerprint
        ),
    )

    return (
        plan,
        manifest,
        approval,
    )


class FakeResolver:
    def __init__(
        self,
        *,
        missing_variants=None,
        location_id=LOCATION_ID,
    ):
        self._missing_variants = set(
            missing_variants or ()
        )
        self._location_id = location_id

    def resolve(
        self,
        shopify_variant_id,
    ):
        if (
            shopify_variant_id
            in self._missing_variants
        ):
            return None

        suffix = (
            shopify_variant_id
            .rsplit("/", 1)[-1]
        )

        return ShopifyInventoryTarget(
            inventory_item_id=(
                "gid://shopify/InventoryItem/"
                + suffix
            ),
            location_id=(
                self._location_id
            ),
        )


class FakeReadback:
    def __init__(
        self,
        *,
        quantities=None,
        sku_overrides=None,
        tracked=True,
        location_active=True,
        level_active=True,
        fail_items=None,
    ):
        self._quantities = {
            "gid://shopify/InventoryItem/1001":
                10,
            "gid://shopify/InventoryItem/1002":
                20,
        }
        self._quantities.update(
            quantities or {}
        )
        self._sku_overrides = (
            sku_overrides or {}
        )
        self._tracked = tracked
        self._location_active = (
            location_active
        )
        self._level_active = (
            level_active
        )
        self._fail_items = set(
            fail_items or ()
        )

    def read_available(
        self,
        *,
        inventory_item_id,
        location_id,
    ):
        if inventory_item_id in self._fail_items:
            raise SupplierExecutionError(
                "synthetic read failure"
            )

        suffix = (
            inventory_item_id
            .rsplit("/", 1)[-1]
        )

        return InventoryReadbackState(
            inventory_item_id=(
                inventory_item_id
            ),
            sku=(
                self._sku_overrides.get(
                    inventory_item_id,
                    f"SKU-{suffix}",
                )
            ),
            tracked=(
                self._tracked
            ),
            location_id=(
                location_id
            ),
            location_name="Demo",
            location_active=(
                self._location_active
            ),
            level_active=(
                self._level_active
            ),
            available_quantity=(
                self._quantities[
                    inventory_item_id
                ]
            ),
        )


def run_preflight(
    *,
    plan=None,
    manifest=None,
    approval=None,
    resolver=None,
    readback=None,
    location_id=LOCATION_ID,
):
    if (
        plan is None
        or manifest is None
        or approval is None
    ):
        (
            plan,
            manifest,
            approval,
        ) = (
            build_manifest_and_approval(
                plan
            )
        )

    return evaluate_live_batch_preflight(
        plan=plan,
        manifest=manifest,
        approval_report=approval,
        target_resolver=(
            resolver
            or FakeResolver()
        ),
        readback_port=(
            readback
            or FakeReadback()
        ),
        expected_location_id=(
            location_id
        ),
    )


def test_hardened_batch_builder_keeps_two_mutations():
    plan = build_plan()

    manifest = build_batch_safety_manifest(
        plan=plan,
        policy=BatchSafetyPolicy(),
    )

    assert len(
        manifest.mutations
    ) == 2


def test_hardened_builder_rejects_missing_current_quantity():
    plan = build_plan()

    malformed = replace(
        plan.items[0],
        current_inventory_quantity=None,
    )

    bad_plan = replace(
        plan,
        items=(
            malformed,
            plan.items[1],
        ),
    )

    with pytest.raises(
        BatchSafetyError,
        match="fails closed",
    ):
        build_batch_safety_manifest(
            plan=bad_plan,
            policy=BatchSafetyPolicy(),
        )


def test_hardened_builder_rejects_missing_proposed_quantity():
    plan = build_plan()

    malformed = replace(
        plan.items[0],
        proposed_inventory_quantity=None,
    )

    bad_plan = replace(
        plan,
        items=(
            malformed,
            plan.items[1],
        ),
    )

    with pytest.raises(
        BatchSafetyError,
        match="fails closed",
    ):
        build_batch_safety_manifest(
            plan=bad_plan,
            policy=BatchSafetyPolicy(),
        )


def test_hardened_builder_rejects_missing_delta():
    plan = build_plan()

    malformed = replace(
        plan.items[0],
        inventory_delta=None,
    )

    bad_plan = replace(
        plan,
        items=(
            malformed,
            plan.items[1],
        ),
    )

    with pytest.raises(
        BatchSafetyError,
        match="fails closed",
    ):
        build_batch_safety_manifest(
            plan=bad_plan,
            policy=BatchSafetyPolicy(),
        )


def test_hardened_builder_rejects_inconsistent_delta():
    plan = build_plan()

    malformed = replace(
        plan.items[0],
        inventory_delta=999,
    )

    bad_plan = replace(
        plan,
        items=(
            malformed,
            plan.items[1],
        ),
    )

    with pytest.raises(
        BatchSafetyError,
        match="inconsistent",
    ):
        build_batch_safety_manifest(
            plan=bad_plan,
            policy=BatchSafetyPolicy(),
        )


def test_hardened_builder_rejects_zero_delta_mutation():
    plan = build_plan()

    malformed = replace(
        plan.items[0],
        proposed_inventory_quantity=10,
        inventory_delta=0,
    )

    bad_plan = replace(
        plan,
        items=(
            malformed,
            plan.items[1],
        ),
    )

    with pytest.raises(
        BatchSafetyError,
        match="zero",
    ):
        build_batch_safety_manifest(
            plan=bad_plan,
            policy=BatchSafetyPolicy(),
        )


def test_strict_identity_accepts_matching_plan_and_manifest():
    plan, manifest, _ = (
        build_manifest_and_approval()
    )

    validate_plan_manifest_identity(
        plan=plan,
        manifest=manifest,
    )


def test_strict_identity_rejects_changed_source_plan_fingerprint():
    plan, manifest, _ = (
        build_manifest_and_approval()
    )

    changed_manifest = replace(
        manifest,
        source_plan_fingerprint=(
            "f" * 64
        ),
    )

    with pytest.raises(
        BatchPreflightError,
        match="source-plan fingerprint",
    ):
        validate_plan_manifest_identity(
            plan=plan,
            manifest=changed_manifest,
        )


def test_strict_identity_rejects_missing_manifest_mutation():
    plan, manifest, _ = (
        build_manifest_and_approval()
    )

    changed_manifest = replace(
        manifest,
        mutations=(
            manifest.mutations[:1]
        ),
    )

    with pytest.raises(
        BatchPreflightError,
        match="count",
    ):
        validate_plan_manifest_identity(
            plan=plan,
            manifest=changed_manifest,
        )


def test_strict_identity_rejects_reordered_manifest():
    plan, manifest, _ = (
        build_manifest_and_approval()
    )

    changed_manifest = replace(
        manifest,
        mutations=tuple(
            reversed(
                manifest.mutations
            )
        ),
    )

    with pytest.raises(
        BatchPreflightError,
        match="identity mismatch",
    ):
        validate_plan_manifest_identity(
            plan=plan,
            manifest=changed_manifest,
        )


def test_matching_live_baseline_is_ready():
    report = run_preflight()

    assert (
        report.status
        == BatchPreflightStatus.READY
    )
    assert report.can_execute is True
    assert report.ready_items == 2


def test_one_drifted_item_makes_batch_stale():
    report = run_preflight(
        readback=FakeReadback(
            quantities={
                "gid://shopify/InventoryItem/1002":
                    18,
            }
        )
    )

    assert (
        report.status
        == BatchPreflightStatus.STALE
    )
    assert report.can_execute is False
    assert report.stale_items == 1


def test_drifted_item_preserves_expected_and_fresh_values():
    report = run_preflight(
        readback=FakeReadback(
            quantities={
                "gid://shopify/InventoryItem/1002":
                    18,
            }
        )
    )

    stale = next(
        item
        for item in report.items
        if (
            item.status
            == BatchPreflightItemStatus.STALE
        )
    )

    assert (
        stale.approved_baseline_quantity
        == 20
    )
    assert stale.fresh_shopify_quantity == 18


def test_multiple_drifted_items_counted():
    report = run_preflight(
        readback=FakeReadback(
            quantities={
                "gid://shopify/InventoryItem/1001":
                    9,
                "gid://shopify/InventoryItem/1002":
                    21,
            }
        )
    )

    assert report.stale_items == 2


def test_missing_target_blocks_batch():
    plan, manifest, approval = (
        build_manifest_and_approval()
    )

    report = run_preflight(
        plan=plan,
        manifest=manifest,
        approval=approval,
        resolver=FakeResolver(
            missing_variants={
                plan.items[0]
                .shopify_variant_id
            }
        ),
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )
    assert report.blocked_items == 1


def test_wrong_resolved_location_blocks_batch():
    report = run_preflight(
        resolver=FakeResolver(
            location_id=(
                "gid://shopify/Location/999002"
            )
        )
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )
    assert (
        BatchPreflightReason
        .TARGET_LOCATION_MISMATCH
        in report.reasons
    )


def test_live_read_failure_blocks_batch():
    report = run_preflight(
        readback=FakeReadback(
            fail_items={
                "gid://shopify/InventoryItem/1001"
            }
        )
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )
    assert (
        BatchPreflightReason.LIVE_READ_FAILED
        in report.reasons
    )


def test_sku_mismatch_blocks_batch():
    report = run_preflight(
        readback=FakeReadback(
            sku_overrides={
                "gid://shopify/InventoryItem/1001":
                    "WRONG-SKU"
            }
        )
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )
    assert (
        BatchPreflightReason.SKU_MISMATCH
        in report.reasons
    )


def test_missing_live_sku_blocks_batch():
    report = run_preflight(
        readback=FakeReadback(
            sku_overrides={
                "gid://shopify/InventoryItem/1001":
                    None
            }
        )
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )


def test_untracked_inventory_blocks_batch():
    report = run_preflight(
        readback=FakeReadback(
            tracked=False
        )
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )
    assert (
        BatchPreflightReason
        .INVENTORY_NOT_TRACKED
        in report.reasons
    )


def test_inactive_location_blocks_batch():
    report = run_preflight(
        readback=FakeReadback(
            location_active=False
        )
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )


def test_inactive_inventory_level_blocks_batch():
    report = run_preflight(
        readback=FakeReadback(
            level_active=False
        )
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )


def test_missing_approval_blocks_before_live_read():
    plan = build_plan()

    manifest = build_batch_safety_manifest(
        plan=plan,
        policy=BatchSafetyPolicy(),
    )

    approval = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=None,
    )

    report = run_preflight(
        plan=plan,
        manifest=manifest,
        approval=approval,
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )
    assert report.items == ()


def test_manifest_approval_mismatch_blocks():
    plan, manifest, approval = (
        build_manifest_and_approval()
    )

    bad_approval = replace(
        approval,
        approved_manifest_fingerprint=(
            "f" * 64
        ),
    )

    report = run_preflight(
        plan=plan,
        manifest=manifest,
        approval=bad_approval,
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )


def test_manifest_mutation_tamper_blocks_without_live_reads():
    plan, manifest, approval = (
        build_manifest_and_approval()
    )

    tampered = replace(
        manifest,
        mutations=(
            replace(
                manifest.mutations[0],
                proposed_inventory_quantity=99,
            ),
            manifest.mutations[1],
        ),
    )

    report = run_preflight(
        plan=plan,
        manifest=tampered,
        approval=approval,
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )
    assert (
        BatchPreflightReason
        .MANIFEST_MUTATION_MISMATCH
        in report.reasons
    )


def test_invalid_location_id_rejected():
    with pytest.raises(
        BatchPreflightError,
        match="Location GID",
    ):
        run_preflight(
            location_id="not-a-location"
        )


def test_ready_report_has_deterministic_fingerprint():
    first = run_preflight()
    second = run_preflight()

    assert (
        first.preflight_fingerprint
        == second.preflight_fingerprint
    )


def test_drift_changes_preflight_fingerprint():
    ready = run_preflight()

    stale = run_preflight(
        readback=FakeReadback(
            quantities={
                "gid://shopify/InventoryItem/1002":
                    18
            }
        )
    )

    assert (
        ready.preflight_fingerprint
        != stale.preflight_fingerprint
    )


def test_preflight_fingerprint_is_sha256_length():
    report = run_preflight()

    assert len(
        report.preflight_fingerprint
    ) == 64


def test_ready_report_reason_is_ready():
    report = run_preflight()

    assert report.reasons == (
        BatchPreflightReason.READY,
    )


def test_stale_report_contains_baseline_drift_reason():
    report = run_preflight(
        readback=FakeReadback(
            quantities={
                "gid://shopify/InventoryItem/1001":
                    11
            }
        )
    )

    assert (
        BatchPreflightReason.BASELINE_DRIFT
        in report.reasons
    )


def test_blocked_precedence_over_stale():
    report = run_preflight(
        readback=FakeReadback(
            quantities={
                "gid://shopify/InventoryItem/1002":
                    18,
            },
            sku_overrides={
                "gid://shopify/InventoryItem/1001":
                    "WRONG"
            },
        )
    )

    assert (
        report.status
        == BatchPreflightStatus.BLOCKED
    )
    assert report.stale_items == 1
    assert report.blocked_items == 1


def test_preflight_preserves_manifest_fingerprint():
    _, manifest, _ = (
        build_manifest_and_approval()
    )

    report = run_preflight()

    assert (
        report.manifest_fingerprint
        == manifest.manifest_fingerprint
    )


def test_preflight_preserves_approved_manifest_fingerprint():
    _, manifest, _ = (
        build_manifest_and_approval()
    )

    report = run_preflight()

    assert (
        report.approved_manifest_fingerprint
        == manifest.manifest_fingerprint
    )


def test_each_ready_item_preserves_proposed_quantity():
    report = run_preflight()

    assert [
        item.proposed_inventory_quantity
        for item in report.items
    ] == [
        15,
        25,
    ]


def test_each_ready_item_preserves_inventory_delta():
    report = run_preflight()

    assert [
        item.inventory_delta
        for item in report.items
    ] == [
        5,
        5,
    ]


def test_strict_identity_detects_changed_shopify_sku():
    plan, manifest, _ = (
        build_manifest_and_approval()
    )

    tampered = replace(
        manifest,
        mutations=(
            replace(
                manifest.mutations[0],
                shopify_sku="OTHER"
            ),
            manifest.mutations[1],
        ),
    )

    with pytest.raises(
        BatchPreflightError,
        match="identity mismatch",
    ):
        validate_plan_manifest_identity(
            plan=plan,
            manifest=tampered,
        )


def test_strict_identity_detects_changed_baseline_quantity():
    plan, manifest, _ = (
        build_manifest_and_approval()
    )

    tampered = replace(
        manifest,
        mutations=(
            replace(
                manifest.mutations[0],
                current_inventory_quantity=9
            ),
            manifest.mutations[1],
        ),
    )

    with pytest.raises(
        BatchPreflightError,
        match="identity mismatch",
    ):
        validate_plan_manifest_identity(
            plan=plan,
            manifest=tampered,
        )


def test_strict_identity_detects_changed_delta():
    plan, manifest, _ = (
        build_manifest_and_approval()
    )

    tampered = replace(
        manifest,
        mutations=(
            replace(
                manifest.mutations[0],
                inventory_delta=6
            ),
            manifest.mutations[1],
        ),
    )

    with pytest.raises(
        BatchPreflightError,
        match="identity mismatch",
    ):
        validate_plan_manifest_identity(
            plan=plan,
            manifest=tampered,
        )


def test_plan_mutation_action_is_set_inventory():
    plan = build_plan()

    assert all(
        item.action
        == SyncPlanAction.SET_INVENTORY
        for item in plan.items
    )


def test_preflight_performs_no_mutation_api_contract():
    report = run_preflight()

    assert report.can_execute is True
    assert not hasattr(
        report,
        "execute"
    )
    assert not hasattr(
        report,
        "apply"
    )
