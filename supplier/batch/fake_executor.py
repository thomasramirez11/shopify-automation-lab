from __future__ import annotations

from dataclasses import dataclass

from supplier.batch.approval import (
    BatchApprovalReport,
)
from supplier.batch.models import (
    BatchSafetyManifest,
    BatchSafetyStatus,
)
from supplier.execution.executor import (
    execute_sync_plan,
)
from supplier.execution.models import (
    SupplierExecutionError,
    SupplierExecutionReport,
)
from supplier.execution.ports import (
    InventoryMutationPort,
)
from supplier.guard.guard import (
    evaluate_execution_guard,
)
from supplier.plan.models import (
    SupplierSyncPlan,
)


@dataclass(frozen=True)
class BatchFakeExecutionReport:
    plan_fingerprint: str
    manifest_fingerprint: str

    planned_mutations: int
    total_absolute_inventory_delta: int

    execution_report: SupplierExecutionReport

    @property
    def succeeded(
        self,
    ) -> bool:
        return (
            self.execution_report.succeeded
        )


def execute_approved_batch_fake(
    *,
    plan: SupplierSyncPlan,
    manifest: BatchSafetyManifest,
    approval_report: BatchApprovalReport,
    inventory_port: InventoryMutationPort,
) -> BatchFakeExecutionReport:
    """
    Execute an approved batch through an injected NON-LIVE mutation port.

    This checkpoint is designed for FakeInventoryMutationAdapter.
    It contains no Shopify implementation.
    """

    if (
        manifest.status
        != BatchSafetyStatus.READY
    ):
        raise SupplierExecutionError(
            "Batch safety manifest is not READY."
        )

    if not approval_report.can_execute:
        raise SupplierExecutionError(
            "Batch approval has not authorized this manifest."
        )

    if (
        manifest.source_plan_fingerprint
        != plan.fingerprint
    ):
        raise SupplierExecutionError(
            "Batch manifest source plan fingerprint does not match plan."
        )

    if (
        approval_report
        .current_manifest_fingerprint
        != manifest.manifest_fingerprint
    ):
        raise SupplierExecutionError(
            "Batch approval report does not match current manifest."
        )

    if (
        approval_report
        .approved_manifest_fingerprint
        != manifest.manifest_fingerprint
    ):
        raise SupplierExecutionError(
            "Approved batch manifest fingerprint does not match."
        )

    # Reuse our already-tested plan executor. The batch approval authorizes
    # the exact manifest; this internal guard authorizes the exact source plan.
    plan_guard = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            plan.fingerprint
        ),
    )

    execution_report = execute_sync_plan(
        plan=plan,
        guard_report=plan_guard,
        inventory_port=inventory_port,
    )

    return BatchFakeExecutionReport(
        plan_fingerprint=(
            plan.fingerprint
        ),
        manifest_fingerprint=(
            manifest.manifest_fingerprint
        ),
        planned_mutations=(
            manifest.planned_mutations
        ),
        total_absolute_inventory_delta=(
            manifest
            .total_absolute_inventory_delta
        ),
        execution_report=(
            execution_report
        ),
    )
