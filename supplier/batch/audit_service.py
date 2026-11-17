from __future__ import annotations

import hashlib

from supplier.batch.audit_models import (
    BatchAuditCompletionResult,
    BatchAuditStartResult,
    BatchExecutionAuditEvent,
    BatchExecutionEventType,
    BatchItemAuditEvent,
    BatchItemEventType,
)
from supplier.batch.audit_repository import (
    SupplierBatchExecutionAuditRepository,
)
from supplier.batch.models import (
    BatchSafetyManifest,
    BatchSafetyStatus,
)
from supplier.execution.models import (
    SupplierExecutionReport,
)
from supplier.plan.models import (
    SupplierSyncPlan,
    SyncPlanAction,
)


class SupplierBatchExecutionAuditService:
    """
    Parent/child append-only audit trail for an approved batch execution.
    """

    def __init__(
        self,
        repository: SupplierBatchExecutionAuditRepository,
    ) -> None:
        self._repository = repository

    def build_batch_id(
        self,
        manifest: BatchSafetyManifest,
    ) -> str:
        payload = (
            "supplier-batch:"
            + manifest.manifest_fingerprint
        )

        return hashlib.sha256(
            payload.encode(
                "utf-8"
            )
        ).hexdigest()

    def build_item_operation_id(
        self,
        *,
        batch_id: str,
        item_index: int,
        shopify_variant_id: str,
        requested_quantity: int,
    ) -> str:
        payload = (
            f"{batch_id}:"
            f"{item_index}:"
            f"{shopify_variant_id}:"
            f"{requested_quantity}"
        )

        return hashlib.sha256(
            payload.encode(
                "utf-8"
            )
        ).hexdigest()

    def start_batch(
        self,
        *,
        plan: SupplierSyncPlan,
        manifest: BatchSafetyManifest,
    ) -> BatchAuditStartResult:
        self._validate_plan_manifest(
            plan=plan,
            manifest=manifest,
        )

        batch_id = self.build_batch_id(
            manifest
        )

        batch_event = (
            self._repository
            .append_batch_event(
                BatchExecutionAuditEvent(
                    batch_id=batch_id,
                    event_type=(
                        BatchExecutionEventType
                        .BATCH_STARTED
                    ),
                    source_plan_fingerprint=(
                        plan.fingerprint
                    ),
                    manifest_fingerprint=(
                        manifest
                        .manifest_fingerprint
                    ),
                    planned_mutations=(
                        manifest
                        .planned_mutations
                    ),
                    total_absolute_inventory_delta=(
                        manifest
                        .total_absolute_inventory_delta
                    ),
                    attempted_mutations=0,
                    applied_mutations=0,
                    failed_mutations=0,
                )
            )
        )

        item_event_ids = []

        for index, item in enumerate(
            manifest.mutations,
            start=1,
        ):
            operation_id = (
                self.build_item_operation_id(
                    batch_id=batch_id,
                    item_index=index,
                    shopify_variant_id=(
                        item.shopify_variant_id
                    ),
                    requested_quantity=(
                        item.proposed_inventory_quantity
                    ),
                )
            )

            result = (
                self._repository
                .append_item_event(
                    BatchItemAuditEvent(
                        batch_id=batch_id,
                        item_index=index,
                        operation_id=(
                            operation_id
                        ),
                        event_type=(
                            BatchItemEventType
                            .ITEM_STARTED
                        ),
                        supplier_sku=(
                            item.supplier_sku
                        ),
                        shopify_variant_id=(
                            item.shopify_variant_id
                        ),
                        shopify_sku=(
                            item.shopify_sku
                        ),
                        before_quantity=(
                            item
                            .current_inventory_quantity
                        ),
                        requested_quantity=(
                            item
                            .proposed_inventory_quantity
                        ),
                        inventory_delta=(
                            item.inventory_delta
                        ),
                    )
                )
            )

            item_event_ids.append(
                result.event_id
            )

        return BatchAuditStartResult(
            batch_id=batch_id,
            batch_event_id=(
                batch_event.event_id
            ),
            item_started_event_ids=(
                tuple(
                    item_event_ids
                )
            ),
        )

    def complete_batch(
        self,
        *,
        plan: SupplierSyncPlan,
        manifest: BatchSafetyManifest,
        execution_report: SupplierExecutionReport,
    ) -> BatchAuditCompletionResult:
        self._validate_plan_manifest(
            plan=plan,
            manifest=manifest,
        )

        if (
            execution_report.plan_fingerprint
            != plan.fingerprint
        ):
            raise ValueError(
                "Execution report plan fingerprint does not match batch plan."
            )

        if (
            execution_report.attempted_mutations
            != manifest.planned_mutations
        ):
            raise ValueError(
                "Execution report attempted mutation count does not match manifest."
            )

        if (
            len(
                execution_report.results
            )
            != len(
                manifest.mutations
            )
        ):
            raise ValueError(
                "Execution result count does not match batch manifest."
            )

        batch_id = self.build_batch_id(
            manifest
        )

        failed_mutations = (
            execution_report.attempted_mutations
            - execution_report.applied_mutations
        )

        if failed_mutations == 0:
            terminal_type = (
                BatchExecutionEventType
                .BATCH_COMPLETED
            )

        elif execution_report.applied_mutations == 0:
            terminal_type = (
                BatchExecutionEventType
                .BATCH_FAILED
            )

        else:
            terminal_type = (
                BatchExecutionEventType
                .BATCH_PARTIAL_FAILURE
            )

        existing_terminal = (
            self._repository
            .get_terminal_batch_event(
                batch_id
            )
        )

        if (
            existing_terminal is not None
            and existing_terminal.event_type
            != terminal_type.value
        ):
            raise ValueError(
                "Batch already has a different terminal execution outcome."
            )

        item_result_event_ids = []

        for index, (
            item,
            result,
        ) in enumerate(
            zip(
                manifest.mutations,
                execution_report.results,
                strict=True,
            ),
            start=1,
        ):
            if (
                result.shopify_variant_id
                != item.shopify_variant_id
                or result.shopify_sku
                != item.shopify_sku
                or result
                .requested_inventory_quantity
                != item
                .proposed_inventory_quantity
            ):
                raise ValueError(
                    "Execution result does not match batch item identity."
                )

            operation_id = (
                self.build_item_operation_id(
                    batch_id=batch_id,
                    item_index=index,
                    shopify_variant_id=(
                        item.shopify_variant_id
                    ),
                    requested_quantity=(
                        item.proposed_inventory_quantity
                    ),
                )
            )

            event_type = (
                BatchItemEventType.ITEM_APPLIED
                if result.applied
                else BatchItemEventType.ITEM_FAILED
            )

            error_message = (
                None
                if result.applied
                else (
                    "Inventory mutation adapter "
                    "reported applied=False."
                )
            )

            existing_outcome = (
                self._repository
                .get_item_outcome_event(
                    batch_id=batch_id,
                    item_index=index,
                )
            )

            if (
                existing_outcome is not None
                and existing_outcome.event_type
                != event_type.value
            ):
                raise ValueError(
                    "Batch item already has a different terminal outcome."
                )

            append_result = (
                self._repository
                .append_item_event(
                    BatchItemAuditEvent(
                        batch_id=batch_id,
                        item_index=index,
                        operation_id=(
                            operation_id
                        ),
                        event_type=event_type,
                        supplier_sku=(
                            item.supplier_sku
                        ),
                        shopify_variant_id=(
                            item.shopify_variant_id
                        ),
                        shopify_sku=(
                            item.shopify_sku
                        ),
                        before_quantity=(
                            item
                            .current_inventory_quantity
                        ),
                        requested_quantity=(
                            item
                            .proposed_inventory_quantity
                        ),
                        inventory_delta=(
                            item.inventory_delta
                        ),
                        error_message=(
                            error_message
                        ),
                    )
                )
            )

            item_result_event_ids.append(
                append_result.event_id
            )

        terminal_event = (
            self._repository
            .append_batch_event(
                BatchExecutionAuditEvent(
                    batch_id=batch_id,
                    event_type=(
                        terminal_type
                    ),
                    source_plan_fingerprint=(
                        plan.fingerprint
                    ),
                    manifest_fingerprint=(
                        manifest
                        .manifest_fingerprint
                    ),
                    planned_mutations=(
                        manifest
                        .planned_mutations
                    ),
                    total_absolute_inventory_delta=(
                        manifest
                        .total_absolute_inventory_delta
                    ),
                    attempted_mutations=(
                        execution_report
                        .attempted_mutations
                    ),
                    applied_mutations=(
                        execution_report
                        .applied_mutations
                    ),
                    failed_mutations=(
                        failed_mutations
                    ),
                )
            )
        )

        return BatchAuditCompletionResult(
            batch_id=batch_id,
            terminal_event_type=(
                terminal_type
            ),
            terminal_event_id=(
                terminal_event.event_id
            ),
            item_result_event_ids=(
                tuple(
                    item_result_event_ids
                )
            ),
        )

    def _validate_plan_manifest(
        self,
        *,
        plan: SupplierSyncPlan,
        manifest: BatchSafetyManifest,
    ) -> None:
        if (
            manifest.status
            != BatchSafetyStatus.READY
        ):
            raise ValueError(
                "Batch audit requires a READY safety manifest."
            )

        if (
            manifest.source_plan_fingerprint
            != plan.fingerprint
        ):
            raise ValueError(
                "Batch manifest source plan fingerprint does not match plan."
            )

        mutation_items = tuple(
            item
            for item in plan.items
            if (
                item.action
                == SyncPlanAction.SET_INVENTORY
            )
        )

        if (
            len(
                mutation_items
            )
            != len(
                manifest.mutations
            )
        ):
            raise ValueError(
                "Batch manifest mutation count does not match source plan."
            )
