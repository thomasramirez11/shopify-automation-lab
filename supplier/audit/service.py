from __future__ import annotations

from supplier.audit.models import (
    SupplierExecutionAuditEvent,
    SupplierExecutionEventType,
)
from supplier.audit.repository import (
    SupplierExecutionAuditRepository,
)
from supplier.execution.models import InventoryMutation
from supplier.execution.shopify_adapter import (
    ShopifyInventoryTarget,
    build_inventory_idempotency_key,
)
from supplier.plan.models import (
    SupplierSyncPlan,
    SyncPlanAction,
)


class SupplierExecutionAuditService:
    """
    Build and persist append-only execution events from one-item sync plans.
    """

    def __init__(
        self,
        repository: SupplierExecutionAuditRepository,
    ) -> None:
        self._repository = repository

    def operation_id_for(
        self,
        *,
        plan: SupplierSyncPlan,
        inventory_item_id: str,
        location_id: str,
    ) -> str:
        item = self._single_item(plan)

        mutation = InventoryMutation(
            shopify_variant_id=item.shopify_variant_id,
            shopify_sku=item.shopify_sku,
            inventory_quantity=item.proposed_inventory_quantity,
            expected_current_quantity=item.current_inventory_quantity,
        )

        target = ShopifyInventoryTarget(
            inventory_item_id=inventory_item_id,
            location_id=location_id,
        )

        return build_inventory_idempotency_key(
            mutation=mutation,
            target=target,
        )

    def record_started(
        self,
        *,
        plan: SupplierSyncPlan,
        inventory_item_id: str,
        location_id: str,
    ):
        return self._record(
            plan=plan,
            inventory_item_id=inventory_item_id,
            location_id=location_id,
            event_type=(
                SupplierExecutionEventType.EXECUTION_STARTED
            ),
            observed_after_quantity=None,
            error_message=None,
        )

    def record_verified(
        self,
        *,
        plan: SupplierSyncPlan,
        inventory_item_id: str,
        location_id: str,
        observed_after_quantity: int,
    ):
        return self._record(
            plan=plan,
            inventory_item_id=inventory_item_id,
            location_id=location_id,
            event_type=(
                SupplierExecutionEventType.EXECUTION_VERIFIED
            ),
            observed_after_quantity=observed_after_quantity,
            error_message=None,
        )

    def record_failed(
        self,
        *,
        plan: SupplierSyncPlan,
        inventory_item_id: str,
        location_id: str,
        error_message: str,
    ):
        return self._record(
            plan=plan,
            inventory_item_id=inventory_item_id,
            location_id=location_id,
            event_type=(
                SupplierExecutionEventType.EXECUTION_FAILED
            ),
            observed_after_quantity=None,
            error_message=error_message,
        )

    def _record(
        self,
        *,
        plan: SupplierSyncPlan,
        inventory_item_id: str,
        location_id: str,
        event_type: SupplierExecutionEventType,
        observed_after_quantity: int | None,
        error_message: str | None,
    ):
        item = self._single_item(plan)

        operation_id = self.operation_id_for(
            plan=plan,
            inventory_item_id=inventory_item_id,
            location_id=location_id,
        )

        started_event = (
            self._repository.get_started_event(
                operation_id
            )
        )

        baseline_sync_run_id = (
            started_event.baseline_sync_run_id
            if started_event is not None
            else self._repository.latest_successful_sync_run_id()
        )

        event = SupplierExecutionAuditEvent(
            operation_id=operation_id,
            event_type=event_type,
            supplier_code=item.supplier_code,
            supplier_sku=item.supplier_sku,
            shopify_variant_id=item.shopify_variant_id,
            shopify_sku=item.shopify_sku,
            inventory_item_id=inventory_item_id,
            location_id=location_id,
            before_quantity=item.current_inventory_quantity,
            requested_quantity=item.proposed_inventory_quantity,
            observed_after_quantity=observed_after_quantity,
            inventory_delta=item.inventory_delta,
            plan_fingerprint=plan.fingerprint,
            idempotency_key=operation_id,
            error_message=error_message,
            baseline_sync_run_id=baseline_sync_run_id,
        )

        return self._repository.append(event)

    def _single_item(
        self,
        plan: SupplierSyncPlan,
    ):
        if (
            len(plan.items) != 1
            or plan.planned_mutations != 1
        ):
            raise ValueError(
                "Execution audit requires exactly one planned mutation."
            )

        item = plan.items[0]

        if (
            item.action
            != SyncPlanAction.SET_INVENTORY
            or item.current_inventory_quantity is None
            or item.proposed_inventory_quantity is None
            or item.inventory_delta is None
        ):
            raise ValueError(
                "Execution audit requires a complete inventory mutation item."
            )

        return item
