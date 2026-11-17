from dataclasses import replace

import pytest

from supplier.decision.models import (
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.execution.fake_adapter import (
    FakeInventoryMutationAdapter,
)
from supplier.execution.live_controller import (
    build_live_confirmation_token,
    execute_controlled_single_variant_write,
    verify_pre_write_state,
)
from supplier.execution.models import (
    SupplierExecutionError,
)
from supplier.execution.readback import (
    INVENTORY_READBACK_QUERY,
    InventoryReadbackState,
    ShopifyInventoryReadbackAdapter,
)
from supplier.guard.guard import (
    evaluate_execution_guard,
)
from supplier.plan.builder import (
    build_dry_run_sync_plan,
)


VARIANT_ID = "gid://shopify/ProductVariant/111"
INVENTORY_ITEM_ID = "gid://shopify/InventoryItem/222"
LOCATION_ID = "gid://shopify/Location/333"


def eligible_decision(
    *,
    sku="AUTO-Cap-001",
    current=1,
    supplier=25,
    delta=24,
    proposed=25,
):
    return SupplierSyncDecision(
        supplier_code="demo_supplier",
        supplier_sku="SUP-CAP-001",
        shopify_variant_id=VARIANT_ID,
        shopify_sku=sku,
        status=SyncDecisionStatus.ELIGIBLE,
        reason=(
            SyncDecisionReason
            .INVENTORY_MISMATCH_WITHIN_LIMIT
        ),
        current_inventory_quantity=current,
        supplier_inventory_quantity=supplier,
        inventory_delta=delta,
        proposed_inventory_quantity=proposed,
    )


def approved_plan():
    plan = build_dry_run_sync_plan(
        [
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


def readback_state(
    *,
    quantity=1,
    tracked=True,
    location_active=True,
    level_active=True,
):
    return InventoryReadbackState(
        inventory_item_id=INVENTORY_ITEM_ID,
        sku="AUTO-Cap-001",
        tracked=tracked,
        location_id=LOCATION_ID,
        location_name="Main Warehouse",
        location_active=location_active,
        level_active=level_active,
        available_quantity=quantity,
    )


class SequencedReadback:
    def __init__(self, states):
        self.states = list(states)
        self.calls = 0

    def read_available(
        self,
        *,
        inventory_item_id,
        location_id,
    ):
        state = self.states[
            self.calls
        ]
        self.calls += 1
        return state


class FakeGraphQLClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def graphql(
        self,
        query,
        variables,
    ):
        self.calls.append(
            (
                query,
                variables,
            )
        )
        return self.response


def test_confirmation_token_is_shell_safe():
    token = build_live_confirmation_token(
        shopify_sku="AUTO-Cap-001",
        proposed_inventory_quantity=25,
    )

    assert token == "LIVE-WRITE-AUTO-Cap-001-TO-25"
    assert "<" not in token
    assert ">" not in token


def test_confirmation_token_rejects_negative_quantity():
    with pytest.raises(
        SupplierExecutionError,
        match="non-negative integer",
    ):
        build_live_confirmation_token(
            shopify_sku="AUTO-Cap-001",
            proposed_inventory_quantity=-1,
        )


def test_pre_write_state_accepts_matching_live_quantity():
    plan, _ = approved_plan()

    verify_pre_write_state(
        plan=plan,
        target_sku="AUTO-Cap-001",
        readback=readback_state(
            quantity=1
        ),
    )


def test_pre_write_state_blocks_stale_live_quantity():
    plan, _ = approved_plan()

    with pytest.raises(
        SupplierExecutionError,
        match="no longer matches",
    ):
        verify_pre_write_state(
            plan=plan,
            target_sku="AUTO-Cap-001",
            readback=readback_state(
                quantity=2
            ),
        )


def test_pre_write_state_blocks_untracked_inventory():
    plan, _ = approved_plan()

    with pytest.raises(
        SupplierExecutionError,
        match="not tracked",
    ):
        verify_pre_write_state(
            plan=plan,
            target_sku="AUTO-Cap-001",
            readback=readback_state(
                tracked=False
            ),
        )


def test_pre_write_state_blocks_inactive_location():
    plan, _ = approved_plan()

    with pytest.raises(
        SupplierExecutionError,
        match="location is not active",
    ):
        verify_pre_write_state(
            plan=plan,
            target_sku="AUTO-Cap-001",
            readback=readback_state(
                location_active=False
            ),
        )


def test_pre_write_state_blocks_inactive_level():
    plan, _ = approved_plan()

    with pytest.raises(
        SupplierExecutionError,
        match="level is not active",
    ):
        verify_pre_write_state(
            plan=plan,
            target_sku="AUTO-Cap-001",
            readback=readback_state(
                level_active=False
            ),
        )


def test_controlled_write_executes_exactly_one_fake_mutation():
    plan, guard = approved_plan()

    adapter = FakeInventoryMutationAdapter()
    readback = SequencedReadback(
        [
            readback_state(
                quantity=1
            ),
            readback_state(
                quantity=25
            ),
        ]
    )

    result = execute_controlled_single_variant_write(
        plan=plan,
        guard_report=guard,
        target_sku="AUTO-Cap-001",
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
        confirmation_token=(
            "LIVE-WRITE-AUTO-Cap-001-TO-25"
        ),
        inventory_port=adapter,
        readback_port=readback,
    )

    assert (
        result.execution_report
        .attempted_mutations
        == 1
    )
    assert (
        result.execution_report
        .applied_mutations
        == 1
    )
    assert (
        result.readback
        .available_quantity
        == 25
    )
    assert len(
        adapter.mutations
    ) == 1


def test_controlled_write_rejects_wrong_confirmation_token():
    plan, guard = approved_plan()

    adapter = FakeInventoryMutationAdapter()

    with pytest.raises(
        SupplierExecutionError,
        match="confirmation token",
    ):
        execute_controlled_single_variant_write(
            plan=plan,
            guard_report=guard,
            target_sku="AUTO-Cap-001",
            inventory_item_id=INVENTORY_ITEM_ID,
            location_id=LOCATION_ID,
            confirmation_token="WRONG",
            inventory_port=adapter,
            readback_port=SequencedReadback(
                [
                    readback_state(
                        quantity=1
                    )
                ]
            ),
        )

    assert adapter.mutations == ()


def test_controlled_write_rejects_unapproved_guard():
    plan = build_dry_run_sync_plan(
        [
            eligible_decision()
        ]
    )

    guard = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=None,
    )

    with pytest.raises(
        SupplierExecutionError,
        match="has not authorized",
    ):
        execute_controlled_single_variant_write(
            plan=plan,
            guard_report=guard,
            target_sku="AUTO-Cap-001",
            inventory_item_id=INVENTORY_ITEM_ID,
            location_id=LOCATION_ID,
            confirmation_token=(
                "LIVE-WRITE-AUTO-Cap-001-TO-25"
            ),
            inventory_port=(
                FakeInventoryMutationAdapter()
            ),
            readback_port=(
                SequencedReadback(
                    [
                        readback_state(
                            quantity=1
                        )
                    ]
                )
            ),
        )


def test_controlled_write_rejects_two_item_plan():
    first = eligible_decision()

    second = replace(
        eligible_decision(
            sku="AUTO-shirt-L",
            current=2,
            supplier=40,
            delta=38,
            proposed=40,
        ),
        supplier_sku="SUP-SHIRT-L",
        shopify_variant_id=(
            "gid://shopify/ProductVariant/999"
        ),
    )

    plan = build_dry_run_sync_plan(
        [
            first,
            second,
        ]
    )

    guard = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    with pytest.raises(
        SupplierExecutionError,
        match="exactly one item",
    ):
        execute_controlled_single_variant_write(
            plan=plan,
            guard_report=guard,
            target_sku="AUTO-Cap-001",
            inventory_item_id=INVENTORY_ITEM_ID,
            location_id=LOCATION_ID,
            confirmation_token=(
                "LIVE-WRITE-AUTO-Cap-001-TO-25"
            ),
            inventory_port=(
                FakeInventoryMutationAdapter()
            ),
            readback_port=(
                SequencedReadback([])
            ),
        )


def test_post_write_readback_mismatch_is_reported():
    plan, guard = approved_plan()

    with pytest.raises(
        SupplierExecutionError,
        match="Post-write verification failed",
    ):
        execute_controlled_single_variant_write(
            plan=plan,
            guard_report=guard,
            target_sku="AUTO-Cap-001",
            inventory_item_id=INVENTORY_ITEM_ID,
            location_id=LOCATION_ID,
            confirmation_token=(
                "LIVE-WRITE-AUTO-Cap-001-TO-25"
            ),
            inventory_port=(
                FakeInventoryMutationAdapter()
            ),
            readback_port=(
                SequencedReadback(
                    [
                        readback_state(
                            quantity=1
                        ),
                        readback_state(
                            quantity=24
                        ),
                    ]
                )
            ),
        )


def test_readback_adapter_reads_available_quantity():
    client = FakeGraphQLClient(
        {
            "inventoryItem": {
                "id": INVENTORY_ITEM_ID,
                "sku": "AUTO-Cap-001",
                "tracked": True,
                "inventoryLevel": {
                    "id": (
                        "gid://shopify/InventoryLevel/1"
                    ),
                    "isActive": True,
                    "location": {
                        "id": LOCATION_ID,
                        "name": "Main Warehouse",
                        "isActive": True,
                    },
                    "quantities": [
                        {
                            "name": "available",
                            "quantity": 25,
                        }
                    ],
                },
            }
        }
    )

    state = (
        ShopifyInventoryReadbackAdapter(
            client
        )
        .read_available(
            inventory_item_id=(
                INVENTORY_ITEM_ID
            ),
            location_id=(
                LOCATION_ID
            ),
        )
    )

    assert state.available_quantity == 25
    assert state.tracked is True
    assert state.level_active is True


def test_readback_adapter_rejects_missing_inventory_level():
    client = FakeGraphQLClient(
        {
            "inventoryItem": {
                "id": INVENTORY_ITEM_ID,
                "sku": "AUTO-Cap-001",
                "tracked": True,
                "inventoryLevel": None,
            }
        }
    )

    with pytest.raises(
        SupplierExecutionError,
        match="not stocked",
    ):
        ShopifyInventoryReadbackAdapter(
            client
        ).read_available(
            inventory_item_id=(
                INVENTORY_ITEM_ID
            ),
            location_id=(
                LOCATION_ID
            ),
        )


def test_readback_adapter_rejects_invalid_quantity():
    client = FakeGraphQLClient(
        {
            "inventoryItem": {
                "id": INVENTORY_ITEM_ID,
                "sku": "AUTO-Cap-001",
                "tracked": True,
                "inventoryLevel": {
                    "id": "level",
                    "isActive": True,
                    "location": {
                        "id": LOCATION_ID,
                        "name": "Main Warehouse",
                        "isActive": True,
                    },
                    "quantities": [
                        {
                            "name": "available",
                            "quantity": "25",
                        }
                    ],
                },
            }
        }
    )

    with pytest.raises(
        SupplierExecutionError,
        match="invalid available quantity",
    ):
        ShopifyInventoryReadbackAdapter(
            client
        ).read_available(
            inventory_item_id=(
                INVENTORY_ITEM_ID
            ),
            location_id=(
                LOCATION_ID
            ),
        )


def test_readback_query_is_read_only():
    normalized = (
        INVENTORY_READBACK_QUERY
        .strip()
        .lower()
    )

    assert normalized.startswith(
        "query"
    )
    assert "mutation " not in normalized
