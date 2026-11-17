import sqlite3
from contextlib import contextmanager

import pytest

from database.supplier_batch_retry_schema import (
    ensure_supplier_batch_retry_schema,
)
from supplier.batch.approval import (
    evaluate_batch_approval,
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
from supplier.batch.retry_models import (
    FailedBatchItem,
    RetryAuditEvent,
    RetryDecisionStatus,
    RetryEventType,
    RetryPolicy,
    RetryPolicyError,
)
from supplier.batch.retry_policy import (
    build_retry_id,
    evaluate_retry_decision,
)
from supplier.batch.retry_repository import (
    SupplierBatchRetryRepository,
)
from supplier.batch.retry_service import (
    SupplierBatchRetryService,
)
from supplier.decision.models import (
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.execution.fake_adapter import (
    FakeInventoryMutationAdapter,
)
from supplier.plan.builder import (
    build_dry_run_sync_plan,
)


VARIANT_A = "gid://shopify/ProductVariant/910001"
VARIANT_B = "gid://shopify/ProductVariant/910002"


def factory():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    @contextmanager
    def connection_factory():
        try:
            yield connection
        finally:
            connection.commit()

    return connection, connection_factory


def demo_plan():
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
                current_inventory_quantity=5,
                supplier_inventory_quantity=8,
                inventory_delta=3,
                proposed_inventory_quantity=8,
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
                current_inventory_quantity=7,
                supplier_inventory_quantity=11,
                inventory_delta=4,
                proposed_inventory_quantity=11,
            ),
        ]
    )


def demo_manifest():
    current_plan = demo_plan()
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


def seed_partial_failure(
    *,
    connection_factory,
):
    current_plan, current_manifest = (
        demo_manifest()
    )

    approval = evaluate_batch_approval(
        plan=current_plan,
        manifest=current_manifest,
        approved_manifest_fingerprint=(
            current_manifest.manifest_fingerprint
        ),
    )

    batch_repository = (
        SupplierBatchExecutionAuditRepository(
            connection_factory=(
                connection_factory
            )
        )
    )

    audit = (
        SupplierBatchExecutionAuditService(
            batch_repository
        )
    )

    audit.start_batch(
        plan=current_plan,
        manifest=current_manifest,
    )

    execution = (
        execute_approved_batch_fake(
            plan=current_plan,
            manifest=current_manifest,
            approval_report=approval,
            inventory_port=(
                FakeInventoryMutationAdapter(
                    fail_variant_ids={
                        VARIANT_B
                    }
                )
            ),
        )
    )

    completion = audit.complete_batch(
        plan=current_plan,
        manifest=current_manifest,
        execution_report=(
            execution.execution_report
        ),
    )

    return (
        current_plan,
        current_manifest,
        completion,
    )


def retry_repository(
    connection_factory,
):
    return SupplierBatchRetryRepository(
        connection_factory=(
            connection_factory
        )
    )


def retry_service(
    connection_factory,
    *,
    max_attempts=3,
):
    repository = retry_repository(
        connection_factory
    )

    return (
        repository,
        SupplierBatchRetryService(
            repository=repository,
            policy=RetryPolicy(
                max_attempts_per_item=(
                    max_attempts
                )
            ),
        ),
    )


def failed_item(
    *,
    error="Inventory mutation adapter reported applied=False.",
):
    return FailedBatchItem(
        source_batch_id="a" * 64,
        item_index=2,
        operation_id="b" * 64,
        shopify_variant_id=VARIANT_B,
        shopify_sku="SKU-B",
        before_quantity=7,
        requested_quantity=11,
        inventory_delta=4,
        original_error_message=error,
    )


def test_schema_creates_retry_table():
    connection, _ = factory()

    ensure_supplier_batch_retry_schema(
        connection
    )

    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'supplier_batch_retry_events';
        """
    ).fetchone()

    assert row is not None


def test_schema_is_idempotent():
    connection, _ = factory()

    ensure_supplier_batch_retry_schema(
        connection
    )
    ensure_supplier_batch_retry_schema(
        connection
    )


def test_retry_ledger_update_is_blocked():
    connection, connection_factory = factory()

    repository = retry_repository(
        connection_factory
    )

    repository.append(
        RetryAuditEvent(
            retry_id="c" * 64,
            source_batch_id="a" * 64,
            item_index=1,
            operation_id="b" * 64,
            shopify_variant_id=VARIANT_A,
            shopify_sku="SKU-A",
            before_quantity=1,
            requested_quantity=2,
            inventory_delta=1,
            attempt_number=1,
            event_type=(
                RetryEventType.RETRY_QUEUED
            ),
        )
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            UPDATE supplier_batch_retry_events
            SET requested_quantity = 99;
            """
        )


def test_retry_ledger_delete_is_blocked():
    connection, connection_factory = factory()

    repository = retry_repository(
        connection_factory
    )

    repository.append(
        RetryAuditEvent(
            retry_id="c" * 64,
            source_batch_id="a" * 64,
            item_index=1,
            operation_id="b" * 64,
            shopify_variant_id=VARIANT_A,
            shopify_sku="SKU-A",
            before_quantity=1,
            requested_quantity=2,
            inventory_delta=1,
            attempt_number=1,
            event_type=(
                RetryEventType.RETRY_QUEUED
            ),
        )
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            DELETE FROM supplier_batch_retry_events;
            """
        )


def test_retry_id_is_deterministic():
    item = failed_item()

    assert (
        build_retry_id(
            item
        )
        == build_retry_id(
            item
        )
    )


def test_retry_policy_queues_retryable_failure():
    decision = evaluate_retry_decision(
        failed_item=failed_item(),
        prior_attempts=0,
        recovered=False,
        exhausted=False,
        policy=RetryPolicy(),
    )

    assert (
        decision.status
        == RetryDecisionStatus.QUEUE
    )
    assert decision.next_attempt_number == 1


def test_retry_policy_rejects_non_retryable_failure():
    decision = evaluate_retry_decision(
        failed_item=failed_item(
            error="invalid credentials"
        ),
        prior_attempts=0,
        recovered=False,
        exhausted=False,
        policy=RetryPolicy(),
    )

    assert (
        decision.status
        == RetryDecisionStatus.NON_RETRYABLE
    )


def test_retry_policy_stops_recovered_item():
    decision = evaluate_retry_decision(
        failed_item=failed_item(),
        prior_attempts=1,
        recovered=True,
        exhausted=False,
        policy=RetryPolicy(),
    )

    assert (
        decision.status
        == RetryDecisionStatus.ALREADY_RECOVERED
    )


def test_retry_policy_exhausts_at_budget():
    decision = evaluate_retry_decision(
        failed_item=failed_item(),
        prior_attempts=3,
        recovered=False,
        exhausted=False,
        policy=RetryPolicy(
            max_attempts_per_item=3
        ),
    )

    assert (
        decision.status
        == RetryDecisionStatus.EXHAUSTED
    )


def test_invalid_max_attempts_rejected():
    with pytest.raises(
        RetryPolicyError,
        match="greater than zero",
    ):
        RetryPolicy(
            max_attempts_per_item=0
        )


def test_partial_failure_discovers_only_failed_item():
    _, connection_factory = factory()

    seed_partial_failure(
        connection_factory=connection_factory
    )

    repository = retry_repository(
        connection_factory
    )

    failed = repository.discover_failed_items()

    assert len(failed) == 1
    assert failed[0].shopify_sku == "SKU-B"


def test_successful_original_item_is_not_retry_candidate():
    _, connection_factory = factory()

    seed_partial_failure(
        connection_factory=connection_factory
    )

    repository = retry_repository(
        connection_factory
    )

    assert all(
        item.shopify_sku != "SKU-A"
        for item
        in repository.discover_failed_items()
    )


def test_queue_adds_one_retry_for_failed_item():
    _, connection_factory = factory()

    seed_partial_failure(
        connection_factory=connection_factory
    )

    repository, service = retry_service(
        connection_factory
    )

    summary = (
        service.queue_eligible_failures()
    )

    assert summary.failed_items_seen == 1
    assert summary.queued == 1
    assert repository.count_events() == 1


def test_queue_is_idempotent_before_execution():
    _, connection_factory = factory()

    seed_partial_failure(
        connection_factory=connection_factory
    )

    repository, service = retry_service(
        connection_factory
    )

    first = (
        service.queue_eligible_failures()
    )
    second = (
        service.queue_eligible_failures()
    )

    assert first.queued == 1
    assert second.queued == 0
    assert repository.count_events() == 1


def test_execute_retry_retries_only_failed_item():
    _, connection_factory = factory()

    seed_partial_failure(
        connection_factory=connection_factory
    )

    _, service = retry_service(
        connection_factory
    )

    service.queue_eligible_failures()

    adapter = (
        FakeInventoryMutationAdapter()
    )

    summary = (
        service.execute_queued_retries(
            inventory_port=adapter
        )
    )

    assert summary.attempted == 1
    assert summary.succeeded == 1
    assert len(adapter.mutations) == 1
    assert (
        adapter.mutations[0].shopify_sku
        == "SKU-B"
    )


def test_successful_retry_records_recovered_timeline():
    _, connection_factory = factory()

    seed_partial_failure(
        connection_factory=connection_factory
    )

    repository, service = retry_service(
        connection_factory
    )

    service.queue_eligible_failures()
    service.execute_queued_retries(
        inventory_port=(
            FakeInventoryMutationAdapter()
        )
    )

    retry_ids = (
        repository.get_recent_retry_ids(
            limit=1
        )
    )
    events = (
        repository.get_retry_events(
            retry_ids[0]
        )
    )

    assert [
        event.event_type
        for event in events
    ] == [
        "retry_queued",
        "retry_started",
        "retry_succeeded",
    ]


def test_recovered_item_is_not_requeued():
    _, connection_factory = factory()

    seed_partial_failure(
        connection_factory=connection_factory
    )

    repository, service = retry_service(
        connection_factory
    )

    service.queue_eligible_failures()
    service.execute_queued_retries(
        inventory_port=(
            FakeInventoryMutationAdapter()
        )
    )

    second = (
        service.queue_eligible_failures()
    )

    assert second.already_recovered == 1
    assert second.queued == 0
    assert repository.count_events() == 3


def test_failed_retry_can_queue_next_attempt():
    _, connection_factory = factory()

    seed_partial_failure(
        connection_factory=connection_factory
    )

    repository, service = retry_service(
        connection_factory,
        max_attempts=3,
    )

    service.queue_eligible_failures()

    first_attempt = (
        service.execute_queued_retries(
            inventory_port=(
                FakeInventoryMutationAdapter(
                    fail_variant_ids={
                        VARIANT_B
                    }
                )
            )
        )
    )

    assert first_attempt.failed == 1

    queue_again = (
        service.queue_eligible_failures()
    )

    assert queue_again.queued == 1

    queued = (
        repository.get_queued_attempts()
    )

    assert (
        queued[0].attempt_number
        == 2
    )


def test_retry_exhausts_on_final_failed_attempt():
    _, connection_factory = factory()

    repository, service = retry_service(
        connection_factory,
        max_attempts=1,
    )

    seed_partial_failure(
        connection_factory=connection_factory
    )

    service.queue_eligible_failures()

    summary = (
        service.execute_queued_retries(
            inventory_port=(
                FakeInventoryMutationAdapter(
                    fail_variant_ids={
                        VARIANT_B
                    }
                )
            )
        )
    )

    assert summary.failed == 1
    assert summary.exhausted_now == 1

    retry_id = (
        repository.get_recent_retry_ids(
            limit=1
        )[0]
    )

    events = (
        repository.get_retry_events(
            retry_id
        )
    )

    assert (
        events[-1].event_type
        == "retry_exhausted"
    )


def test_exhausted_item_is_not_requeued():
    _, connection_factory = factory()

    seed_partial_failure(
        connection_factory=connection_factory
    )

    _, service = retry_service(
        connection_factory,
        max_attempts=1,
    )

    service.queue_eligible_failures()

    service.execute_queued_retries(
        inventory_port=(
            FakeInventoryMutationAdapter(
                fail_variant_ids={
                    VARIANT_B
                }
            )
        )
    )

    again = (
        service.queue_eligible_failures()
    )

    assert again.exhausted == 1
    assert again.queued == 0


def test_non_retryable_failure_is_recorded_as_skipped():
    connection, connection_factory = factory()

    ensure_supplier_batch_retry_schema(
        connection
    )

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
        VALUES (
            ?, 1, ?, 'item_failed',
            ?, ?, ?,
            1, 2, 1,
            ?
        );
        """,
        (
            "a" * 64,
            "b" * 64,
            "SUP-X",
            VARIANT_A,
            "SKU-X",
            "invalid credentials",
        ),
    )
    connection.commit()

    repository, service = retry_service(
        connection_factory
    )

    summary = (
        service.queue_eligible_failures()
    )

    assert summary.non_retryable == 1
    assert repository.count_events() == 1

    retry_id = (
        repository.get_recent_retry_ids(
            limit=1
        )[0]
    )

    assert (
        repository
        .get_retry_events(
            retry_id
        )[0]
        .event_type
        == "retry_skipped"
    )


def test_retry_attempt_outcome_conflict_is_blocked():
    connection, connection_factory = factory()

    repository = retry_repository(
        connection_factory
    )

    base = RetryAuditEvent(
        retry_id="c" * 64,
        source_batch_id="a" * 64,
        item_index=1,
        operation_id="b" * 64,
        shopify_variant_id=VARIANT_A,
        shopify_sku="SKU-A",
        before_quantity=1,
        requested_quantity=2,
        inventory_delta=1,
        attempt_number=1,
        event_type=(
            RetryEventType.RETRY_SUCCEEDED
        ),
    )

    repository.append(
        base
    )

    with pytest.raises(
        sqlite3.IntegrityError,
    ):
        connection.execute(
            """
            INSERT INTO supplier_batch_retry_events (
                retry_id,
                source_batch_id,
                item_index,
                operation_id,
                shopify_variant_id,
                shopify_sku,
                before_quantity,
                requested_quantity,
                inventory_delta,
                attempt_number,
                event_type,
                error_message
            )
            VALUES (
                ?, ?, 1, ?,
                ?, ?,
                1, 2, 1,
                1,
                'retry_failed',
                'conflict'
            );
            """,
            (
                "c" * 64,
                "a" * 64,
                "b" * 64,
                VARIANT_A,
                "SKU-A",
            ),
        )


def test_no_failed_items_means_empty_queue():
    _, connection_factory = factory()

    _, service = retry_service(
        connection_factory
    )

    summary = (
        service.queue_eligible_failures()
    )

    assert summary.failed_items_seen == 0
    assert summary.queued == 0


def test_get_queued_attempts_empty_after_success():
    _, connection_factory = factory()

    seed_partial_failure(
        connection_factory=connection_factory
    )

    repository, service = retry_service(
        connection_factory
    )

    service.queue_eligible_failures()
    service.execute_queued_retries(
        inventory_port=(
            FakeInventoryMutationAdapter()
        )
    )

    assert (
        repository.get_queued_attempts()
        == []
    )


def test_retry_preview_limit_validation():
    _, connection_factory = factory()

    repository = retry_repository(
        connection_factory
    )

    with pytest.raises(
        ValueError,
        match="positive integer",
    ):
        repository.get_recent_retry_ids(
            limit=0
        )
