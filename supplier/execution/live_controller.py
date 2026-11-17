from __future__ import annotations

from dataclasses import dataclass

from supplier.execution.executor import execute_sync_plan
from supplier.execution.models import (
    SupplierExecutionError,
    SupplierExecutionReport,
)
from supplier.execution.ports import InventoryMutationPort
from supplier.execution.readback import (
    InventoryReadbackPort,
    InventoryReadbackState,
)
from supplier.guard.models import ExecutionGuardReport
from supplier.plan.models import (
    SupplierSyncPlan,
    SyncPlanAction,
)


@dataclass(frozen=True)
class ControlledLiveWriteResult:
    execution_report: SupplierExecutionReport
    before_readback: InventoryReadbackState
    readback: InventoryReadbackState

    @property
    def verified(self) -> bool:
        return self.execution_report.succeeded


def build_live_confirmation_token(
    *,
    shopify_sku: str,
    proposed_inventory_quantity: int,
) -> str:
    sku = shopify_sku.strip()

    if not sku:
        raise SupplierExecutionError(
            "shopify_sku cannot be empty."
        )

    if (
        isinstance(proposed_inventory_quantity, bool)
        or not isinstance(proposed_inventory_quantity, int)
        or proposed_inventory_quantity < 0
    ):
        raise SupplierExecutionError(
            "proposed_inventory_quantity must be a non-negative integer."
        )

    return f"LIVE-WRITE-{sku}-TO-{proposed_inventory_quantity}"


def verify_pre_write_state(
    *,
    plan: SupplierSyncPlan,
    target_sku: str,
    readback: InventoryReadbackState,
) -> None:
    item = _single_mutation_item(
        plan=plan,
        target_sku=target_sku,
    )

    if not readback.tracked:
        raise SupplierExecutionError(
            "Target Shopify inventory item is not tracked."
        )

    if not readback.location_active:
        raise SupplierExecutionError(
            "Target Shopify location is not active."
        )

    if not readback.level_active:
        raise SupplierExecutionError(
            "Target Shopify inventory level is not active."
        )

    if readback.available_quantity != item.current_inventory_quantity:
        raise SupplierExecutionError(
            "Live Shopify inventory no longer matches the approved plan. "
            f"Plan expected {item.current_inventory_quantity}, "
            f"Shopify reports {readback.available_quantity}."
        )


def execute_controlled_single_variant_write(
    *,
    plan: SupplierSyncPlan,
    guard_report: ExecutionGuardReport,
    target_sku: str,
    inventory_item_id: str,
    location_id: str,
    confirmation_token: str,
    inventory_port: InventoryMutationPort,
    readback_port: InventoryReadbackPort,
) -> ControlledLiveWriteResult:
    item = _single_mutation_item(
        plan=plan,
        target_sku=target_sku,
    )

    expected_token = build_live_confirmation_token(
        shopify_sku=item.shopify_sku,
        proposed_inventory_quantity=item.proposed_inventory_quantity,
    )

    if confirmation_token.strip() != expected_token:
        raise SupplierExecutionError(
            "Live-write confirmation token does not match this plan."
        )

    if not guard_report.can_execute:
        raise SupplierExecutionError(
            "Execution guard has not authorized this plan."
        )

    before = readback_port.read_available(
        inventory_item_id=inventory_item_id,
        location_id=location_id,
    )

    verify_pre_write_state(
        plan=plan,
        target_sku=target_sku,
        readback=before,
    )

    report = execute_sync_plan(
        plan=plan,
        guard_report=guard_report,
        inventory_port=inventory_port,
    )

    if not report.succeeded:
        raise SupplierExecutionError(
            "Shopify mutation adapter did not report complete success."
        )

    after = readback_port.read_available(
        inventory_item_id=inventory_item_id,
        location_id=location_id,
    )

    if after.available_quantity != item.proposed_inventory_quantity:
        raise SupplierExecutionError(
            "Post-write verification failed. "
            f"Expected {item.proposed_inventory_quantity}, "
            f"Shopify reports {after.available_quantity}."
        )

    return ControlledLiveWriteResult(
        execution_report=report,
        before_readback=before,
        readback=after,
    )


def _single_mutation_item(
    *,
    plan: SupplierSyncPlan,
    target_sku: str,
):
    if len(plan.items) != 1:
        raise SupplierExecutionError(
            "Controlled live-write plan must contain exactly one item."
        )

    if plan.planned_mutations != 1:
        raise SupplierExecutionError(
            "Controlled live-write plan must contain exactly one mutation."
        )

    item = plan.items[0]

    if item.action != SyncPlanAction.SET_INVENTORY:
        raise SupplierExecutionError(
            "Controlled live-write item is not an inventory mutation."
        )

    if item.shopify_sku != target_sku.strip():
        raise SupplierExecutionError(
            "Controlled live-write target SKU does not match the plan."
        )

    if item.current_inventory_quantity is None:
        raise SupplierExecutionError(
            "Controlled live-write plan is missing current inventory."
        )

    if item.proposed_inventory_quantity is None:
        raise SupplierExecutionError(
            "Controlled live-write plan is missing proposed inventory."
        )

    return item
