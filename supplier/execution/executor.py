from __future__ import annotations

from supplier.execution.models import (
    InventoryMutation,
    SupplierExecutionError,
    SupplierExecutionReport,
)
from supplier.execution.ports import InventoryMutationPort
from supplier.guard.models import ExecutionGuardReport
from supplier.plan.models import (
    SupplierSyncPlan,
    SyncPlanAction,
    SyncPlanMode,
)


def execute_sync_plan(
    *,
    plan: SupplierSyncPlan,
    guard_report: ExecutionGuardReport,
    inventory_port: InventoryMutationPort,
) -> SupplierExecutionReport:
    """
    Execute one approved plan through an injected mutation port.

    The observed current inventory is forwarded so a real Shopify adapter can
    use API-level compare-and-swap protection.
    """

    if plan.mode != SyncPlanMode.DRY_RUN:
        raise SupplierExecutionError(
            "Executor only accepts plans produced by the V2 dry-run planner."
        )

    if not guard_report.can_execute:
        raise SupplierExecutionError(
            "Execution guard has not authorized this plan."
        )

    if guard_report.current_plan_fingerprint != plan.fingerprint:
        raise SupplierExecutionError(
            "Guard current fingerprint does not match the execution plan."
        )

    if guard_report.approved_plan_fingerprint != plan.fingerprint:
        raise SupplierExecutionError(
            "Approved fingerprint does not match the execution plan."
        )

    results = []

    for item in plan.items:
        if item.action != SyncPlanAction.SET_INVENTORY:
            continue

        if item.proposed_inventory_quantity is None:
            raise SupplierExecutionError(
                "SET_INVENTORY plan item is missing proposed inventory."
            )

        if item.current_inventory_quantity is None:
            raise SupplierExecutionError(
                "SET_INVENTORY plan item is missing current inventory."
            )

        mutation = InventoryMutation(
            shopify_variant_id=item.shopify_variant_id,
            shopify_sku=item.shopify_sku,
            inventory_quantity=item.proposed_inventory_quantity,
            expected_current_quantity=item.current_inventory_quantity,
        )

        results.append(
            inventory_port.set_inventory(mutation)
        )

    result_tuple = tuple(results)

    return SupplierExecutionReport(
        plan_fingerprint=plan.fingerprint,
        attempted_mutations=len(result_tuple),
        applied_mutations=sum(
            1 for result in result_tuple if result.applied
        ),
        results=result_tuple,
    )
