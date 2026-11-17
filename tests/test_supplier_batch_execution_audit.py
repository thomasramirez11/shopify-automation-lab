import sqlite3
from contextlib import contextmanager

import pytest

from database.supplier_batch_execution_schema import (
    ensure_supplier_batch_execution_schema,
)
from supplier.batch.approval import (
    evaluate_batch_approval,
)
from supplier.batch.audit_models import (
    BatchAuditError,
    BatchExecutionAuditEvent,
    BatchExecutionEventType,
    BatchItemAuditEvent,
    BatchItemEventType,
)
from supplier.batch.audit_repository import (
    SupplierBatchExecutionAuditRepository,
)
from supplier.batch.audit_service import (
    SupplierBatchExecutionAuditService,
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
    SupplierExecutionReport,
)
from supplier.plan.builder import (
    build_dry_run_sync_plan,
)


VARIANT_A = "gid://shopify/ProductVariant/900001"
VARIANT_B = "gid://shopify/ProductVariant/900002"


def connection_factory():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    @contextmanager
    def factory():
        try:
            yield connection
        finally:
            connection.commit()

    return connection, factory


def plan():
    return build_dry_run_sync_plan(
        [
            SupplierSyncDecision(
                supplier_code="demo_supplier",
                supplier_sku="SUP-A",
                shopify_variant_id=VARIANT_A,
                shopify_sku="SKU-A",
                status=SyncDecisionStatus.ELIGIBLE,
                reason=(
                    SyncDecisionReason
                    .INVENTORY_MISMATCH_WITHIN_LIMIT
                ),
                current_inventory_quantity=10,
                supplier_inventory_quantity=15,
                inventory_delta=5,
                proposed_inventory_quantity=15,
            ),
            SupplierSyncDecision(
                supplier_code="demo_supplier",
                supplier_sku="SUP-B",
                shopify_variant_id=VARIANT_B,
                shopify_sku="SKU-B",
                status=SyncDecisionStatus.ELIGIBLE,
                reason=(
                    SyncDecisionReason
                    .INVENTORY_MISMATCH_WITHIN_LIMIT
                ),
                current_inventory_quantity=20,
                supplier_inventory_quantity=32,
                inventory_delta=12,
                proposed_inventory_quantity=32,
            ),
        ]
    )


def manifest():
    current_plan = plan()

    current_manifest = (
        build_batch_safety_manifest(
            plan=current_plan,
            policy=BatchSafetyPolicy(
                max_mutations_per_batch=5,
                max_total_absolute_inventory_delta=100,
                max_single_item_absolute_delta=50,
            ),
        )
    )

    return current_plan, current_manifest


def approved_execution(
    *,
    fail_variant_ids=None,
):
    current_plan, current_manifest = (
        manifest()
    )

    approval = evaluate_batch_approval(
        plan=current_plan,
        manifest=current_manifest,
        approved_manifest_fingerprint=(
            current_manifest.manifest_fingerprint
        ),
    )

    execution = execute_approved_batch_fake(
        plan=current_plan,
        manifest=current_manifest,
        approval_report=approval,
        inventory_port=(
            FakeInventoryMutationAdapter(
                fail_variant_ids=(
                    fail_variant_ids
                    or set()
                )
            )
        ),
    )

    return (
        current_plan,
        current_manifest,
        execution.execution_report,
    )


def test_schema_creates_parent_and_child_tables():
    connection, _ = connection_factory()

    ensure_supplier_batch_execution_schema(
        connection
    )

    names = {
        row["name"]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table';
            """
        ).fetchall()
    }

    assert (
        "supplier_batch_execution_events"
        in names
    )
    assert (
        "supplier_batch_item_events"
        in names
    )


def test_schema_is_idempotent():
    connection, _ = connection_factory()

    ensure_supplier_batch_execution_schema(
        connection
    )
    ensure_supplier_batch_execution_schema(
        connection
    )


def test_parent_update_is_blocked():
    connection, factory = connection_factory()
    repository = (
        SupplierBatchExecutionAuditRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierBatchExecutionAuditService(
            repository
        )
    )

    current_plan, current_manifest = manifest()
    service.start_batch(
        plan=current_plan,
        manifest=current_manifest,
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            UPDATE supplier_batch_execution_events
            SET applied_mutations = 9;
            """
        )


def test_child_delete_is_blocked():
    connection, factory = connection_factory()
    repository = (
        SupplierBatchExecutionAuditRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierBatchExecutionAuditService(
            repository
        )
    )

    current_plan, current_manifest = manifest()
    service.start_batch(
        plan=current_plan,
        manifest=current_manifest,
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            DELETE FROM supplier_batch_item_events;
            """
        )


def test_batch_id_is_deterministic():
    _, factory = connection_factory()
    service = (
        SupplierBatchExecutionAuditService(
            SupplierBatchExecutionAuditRepository(
                connection_factory=factory
            )
        )
    )

    _, current_manifest = manifest()

    assert (
        service.build_batch_id(
            current_manifest
        )
        == service.build_batch_id(
            current_manifest
        )
    )


def test_item_operation_ids_are_deterministic_and_unique():
    _, factory = connection_factory()
    service = (
        SupplierBatchExecutionAuditService(
            SupplierBatchExecutionAuditRepository(
                connection_factory=factory
            )
        )
    )

    _, current_manifest = manifest()
    batch_id = service.build_batch_id(
        current_manifest
    )

    first = service.build_item_operation_id(
        batch_id=batch_id,
        item_index=1,
        shopify_variant_id=VARIANT_A,
        requested_quantity=15,
    )

    again = service.build_item_operation_id(
        batch_id=batch_id,
        item_index=1,
        shopify_variant_id=VARIANT_A,
        requested_quantity=15,
    )

    second = service.build_item_operation_id(
        batch_id=batch_id,
        item_index=2,
        shopify_variant_id=VARIANT_B,
        requested_quantity=32,
    )

    assert first == again
    assert first != second


def test_start_batch_records_parent_and_two_children():
    _, factory = connection_factory()
    repository = (
        SupplierBatchExecutionAuditRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierBatchExecutionAuditService(
            repository
        )
    )

    current_plan, current_manifest = manifest()

    result = service.start_batch(
        plan=current_plan,
        manifest=current_manifest,
    )

    assert result.batch_event_id == 1
    assert len(
        result.item_started_event_ids
    ) == 2
    assert repository.count_batch_events() == 1
    assert repository.count_item_events() == 2


def test_repeated_start_is_idempotent():
    _, factory = connection_factory()
    repository = (
        SupplierBatchExecutionAuditRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierBatchExecutionAuditService(
            repository
        )
    )

    current_plan, current_manifest = manifest()

    first = service.start_batch(
        plan=current_plan,
        manifest=current_manifest,
    )
    second = service.start_batch(
        plan=current_plan,
        manifest=current_manifest,
    )

    assert first.batch_event_id == second.batch_event_id
    assert (
        first.item_started_event_ids
        == second.item_started_event_ids
    )
    assert repository.count_batch_events() == 1
    assert repository.count_item_events() == 2


def test_successful_completion_records_applied_items_and_completed_batch():
    _, factory = connection_factory()
    repository = (
        SupplierBatchExecutionAuditRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierBatchExecutionAuditService(
            repository
        )
    )

    current_plan, current_manifest, report = (
        approved_execution()
    )

    service.start_batch(
        plan=current_plan,
        manifest=current_manifest,
    )

    completion = service.complete_batch(
        plan=current_plan,
        manifest=current_manifest,
        execution_report=report,
    )

    assert (
        completion.terminal_event_type
        == BatchExecutionEventType.BATCH_COMPLETED
    )
    assert repository.count_batch_events() == 2
    assert repository.count_item_events() == 4


def test_partial_failure_records_partial_terminal_status():
    _, factory = connection_factory()
    repository = (
        SupplierBatchExecutionAuditRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierBatchExecutionAuditService(
            repository
        )
    )

    current_plan, current_manifest, report = (
        approved_execution(
            fail_variant_ids={
                VARIANT_B
            }
        )
    )

    service.start_batch(
        plan=current_plan,
        manifest=current_manifest,
    )

    completion = service.complete_batch(
        plan=current_plan,
        manifest=current_manifest,
        execution_report=report,
    )

    assert (
        completion.terminal_event_type
        == (
            BatchExecutionEventType
            .BATCH_PARTIAL_FAILURE
        )
    )

    item_events = (
        repository.get_item_events(
            completion.batch_id
        )
    )

    assert any(
        event.event_type == "item_failed"
        for event in item_events
    )


def test_all_failed_records_batch_failed():
    _, factory = connection_factory()
    repository = (
        SupplierBatchExecutionAuditRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierBatchExecutionAuditService(
            repository
        )
    )

    current_plan, current_manifest, report = (
        approved_execution(
            fail_variant_ids={
                VARIANT_A,
                VARIANT_B,
            }
        )
    )

    service.start_batch(
        plan=current_plan,
        manifest=current_manifest,
    )

    completion = service.complete_batch(
        plan=current_plan,
        manifest=current_manifest,
        execution_report=report,
    )

    assert (
        completion.terminal_event_type
        == BatchExecutionEventType.BATCH_FAILED
    )


def test_completion_is_idempotent():
    _, factory = connection_factory()
    repository = (
        SupplierBatchExecutionAuditRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierBatchExecutionAuditService(
            repository
        )
    )

    current_plan, current_manifest, report = (
        approved_execution()
    )

    service.start_batch(
        plan=current_plan,
        manifest=current_manifest,
    )

    first = service.complete_batch(
        plan=current_plan,
        manifest=current_manifest,
        execution_report=report,
    )

    second = service.complete_batch(
        plan=current_plan,
        manifest=current_manifest,
        execution_report=report,
    )

    assert first.terminal_event_id == second.terminal_event_id
    assert (
        first.item_result_event_ids
        == second.item_result_event_ids
    )
    assert repository.count_batch_events() == 2
    assert repository.count_item_events() == 4


def test_wrong_execution_report_fingerprint_is_rejected():
    _, factory = connection_factory()
    service = (
        SupplierBatchExecutionAuditService(
            SupplierBatchExecutionAuditRepository(
                connection_factory=factory
            )
        )
    )

    current_plan, current_manifest, report = (
        approved_execution()
    )

    tampered = SupplierExecutionReport(
        plan_fingerprint="f" * 64,
        attempted_mutations=(
            report.attempted_mutations
        ),
        applied_mutations=(
            report.applied_mutations
        ),
        results=(
            report.results
        ),
    )

    with pytest.raises(
        ValueError,
        match="fingerprint",
    ):
        service.complete_batch(
            plan=current_plan,
            manifest=current_manifest,
            execution_report=tampered,
        )


def test_wrong_attempted_count_is_rejected():
    _, factory = connection_factory()
    service = (
        SupplierBatchExecutionAuditService(
            SupplierBatchExecutionAuditRepository(
                connection_factory=factory
            )
        )
    )

    current_plan, current_manifest, report = (
        approved_execution()
    )

    tampered = SupplierExecutionReport(
        plan_fingerprint=(
            report.plan_fingerprint
        ),
        attempted_mutations=1,
        applied_mutations=1,
        results=(
            report.results[:1]
        ),
    )

    with pytest.raises(
        ValueError,
        match="attempted mutation count",
    ):
        service.complete_batch(
            plan=current_plan,
            manifest=current_manifest,
            execution_report=tampered,
        )


def test_result_identity_mismatch_is_rejected():
    _, factory = connection_factory()
    service = (
        SupplierBatchExecutionAuditService(
            SupplierBatchExecutionAuditRepository(
                connection_factory=factory
            )
        )
    )

    current_plan, current_manifest, report = (
        approved_execution()
    )

    first_result = report.results[0]

    tampered_first = type(
        first_result
    )(
        shopify_variant_id=VARIANT_B,
        shopify_sku=(
            first_result.shopify_sku
        ),
        requested_inventory_quantity=(
            first_result
            .requested_inventory_quantity
        ),
        applied=True,
    )

    tampered = SupplierExecutionReport(
        plan_fingerprint=(
            report.plan_fingerprint
        ),
        attempted_mutations=2,
        applied_mutations=2,
        results=(
            tampered_first,
            report.results[1],
        ),
    )

    with pytest.raises(
        ValueError,
        match="identity",
    ):
        service.complete_batch(
            plan=current_plan,
            manifest=current_manifest,
            execution_report=tampered,
        )


def test_not_ready_manifest_is_rejected():
    _, factory = connection_factory()
    service = (
        SupplierBatchExecutionAuditService(
            SupplierBatchExecutionAuditRepository(
                connection_factory=factory
            )
        )
    )

    current_plan = plan()

    blocked_manifest = (
        build_batch_safety_manifest(
            plan=current_plan,
            policy=BatchSafetyPolicy(
                max_mutations_per_batch=1,
                max_total_absolute_inventory_delta=100,
                max_single_item_absolute_delta=50,
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match="READY",
    ):
        service.start_batch(
            plan=current_plan,
            manifest=blocked_manifest,
        )


def test_recent_batch_ids_returns_latest_first():
    _, factory = connection_factory()
    repository = (
        SupplierBatchExecutionAuditRepository(
            connection_factory=factory
        )
    )

    repository.ensure_schema()

    repository.append_batch_event(
        BatchExecutionAuditEvent(
            batch_id="a" * 64,
            event_type=(
                BatchExecutionEventType.BATCH_STARTED
            ),
            source_plan_fingerprint="b" * 64,
            manifest_fingerprint="c" * 64,
            planned_mutations=1,
            total_absolute_inventory_delta=1,
            attempted_mutations=0,
            applied_mutations=0,
            failed_mutations=0,
        )
    )

    repository.append_batch_event(
        BatchExecutionAuditEvent(
            batch_id="d" * 64,
            event_type=(
                BatchExecutionEventType.BATCH_STARTED
            ),
            source_plan_fingerprint="e" * 64,
            manifest_fingerprint="f" * 64,
            planned_mutations=1,
            total_absolute_inventory_delta=1,
            attempted_mutations=0,
            applied_mutations=0,
            failed_mutations=0,
        )
    )

    assert (
        repository.get_recent_batch_ids(
            limit=2
        )
        == [
            "d" * 64,
            "a" * 64,
        ]
    )


def test_recent_batch_limit_validation():
    _, factory = connection_factory()
    repository = (
        SupplierBatchExecutionAuditRepository(
            connection_factory=factory
        )
    )

    with pytest.raises(
        ValueError,
        match="positive integer",
    ):
        repository.get_recent_batch_ids(
            limit=0
        )


def test_failed_item_requires_error_message():
    with pytest.raises(
        BatchAuditError,
        match="requires error_message",
    ):
        BatchItemAuditEvent(
            batch_id="a" * 64,
            item_index=1,
            operation_id="b" * 64,
            event_type=(
                BatchItemEventType.ITEM_FAILED
            ),
            supplier_sku="SUP-A",
            shopify_variant_id=VARIANT_A,
            shopify_sku="SKU-A",
            before_quantity=1,
            requested_quantity=2,
            inventory_delta=1,
        )


def test_invalid_batch_id_is_rejected():
    with pytest.raises(
        BatchAuditError,
        match="64-character",
    ):
        BatchExecutionAuditEvent(
            batch_id="bad",
            event_type=(
                BatchExecutionEventType.BATCH_STARTED
            ),
            source_plan_fingerprint="b" * 64,
            manifest_fingerprint="c" * 64,
            planned_mutations=1,
            total_absolute_inventory_delta=1,
            attempted_mutations=0,
            applied_mutations=0,
            failed_mutations=0,
        )


def test_applied_plus_failed_cannot_exceed_attempted():
    with pytest.raises(
        BatchAuditError,
        match="cannot exceed attempted",
    ):
        BatchExecutionAuditEvent(
            batch_id="a" * 64,
            event_type=(
                BatchExecutionEventType.BATCH_COMPLETED
            ),
            source_plan_fingerprint="b" * 64,
            manifest_fingerprint="c" * 64,
            planned_mutations=2,
            total_absolute_inventory_delta=2,
            attempted_mutations=1,
            applied_mutations=1,
            failed_mutations=1,
        )


def test_conflicting_batch_terminal_outcome_is_rejected():
    _, factory = connection_factory()
    repository = SupplierBatchExecutionAuditRepository(
        connection_factory=factory
    )
    service = SupplierBatchExecutionAuditService(
        repository
    )

    current_plan, current_manifest, success_report = (
        approved_execution()
    )

    service.start_batch(
        plan=current_plan,
        manifest=current_manifest,
    )
    service.complete_batch(
        plan=current_plan,
        manifest=current_manifest,
        execution_report=success_report,
    )

    _, _, partial_report = approved_execution(
        fail_variant_ids={
            VARIANT_B
        }
    )

    with pytest.raises(
        ValueError,
        match="different terminal execution outcome",
    ):
        service.complete_batch(
            plan=current_plan,
            manifest=current_manifest,
            execution_report=partial_report,
        )


def test_conflicting_item_outcome_is_protected_by_unique_index():
    connection, factory = connection_factory()
    repository = SupplierBatchExecutionAuditRepository(
        connection_factory=factory
    )
    repository.ensure_schema()

    batch_id = "a" * 64
    operation_id = "b" * 64

    repository.append_item_event(
        BatchItemAuditEvent(
            batch_id=batch_id,
            item_index=1,
            operation_id=operation_id,
            event_type=BatchItemEventType.ITEM_APPLIED,
            supplier_sku="SUP-A",
            shopify_variant_id=VARIANT_A,
            shopify_sku="SKU-A",
            before_quantity=1,
            requested_quantity=2,
            inventory_delta=1,
        )
    )

    with pytest.raises(
        sqlite3.IntegrityError,
    ):
        connection.execute(
            """
            INSERT INTO supplier_batch_item_events (
                batch_id,
                item_index,
                operation_id,
                event_type,
                supplier_sku,
                shopify_variant_id,
                shopify_sku,
                before_quantity,
                requested_quantity,
                inventory_delta,
                error_message
            )
            VALUES (?, 1, ?, 'item_failed', ?, ?, ?, 1, 2, 1, ?);
            """,
            (
                batch_id,
                operation_id,
                "SUP-A",
                VARIANT_A,
                "SKU-A",
                "conflicting result",
            ),
        )
