import hashlib
import sqlite3
from contextlib import contextmanager

import pytest

from database.supplier_case_resolution_schema import (
    ensure_supplier_case_resolution_schema,
)
from supplier.batch.case_resolution_models import (
    ResolutionCode,
)
from supplier.batch.case_resolution_repository import (
    SupplierCaseResolutionRepository,
)
from supplier.batch.case_resolution_service import (
    SupplierCaseResolutionService,
)
from supplier.batch.dead_letter_repository import (
    SupplierDeadLetterRepository,
)
from supplier.batch.dead_letter_service import (
    SupplierDeadLetterService,
)
from supplier.batch.retry_models import (
    RetryAuditEvent,
    RetryEventType,
)
from supplier.batch.retry_repository import (
    SupplierBatchRetryRepository,
)
from supplier.execution.fake_adapter import (
    FakeInventoryMutationAdapter,
)
from supplier.orchestration.operator_models import (
    OperatorWorkflowError,
)
from supplier.orchestration.operator_workflow import (
    SupplierOperatorWorkflow,
)


def digest(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


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

    return (
        connection,
        connection_factory,
    )


def seed_terminal_retry(
    *,
    connection_factory,
    retry_id: str,
    sku: str,
    variant_suffix: str,
    event_type,
    error_message=None,
    before_quantity=4,
    requested_quantity=9,
):
    repo = SupplierBatchRetryRepository(
        connection_factory=(
            connection_factory
        )
    )

    repo.append(
        RetryAuditEvent(
            retry_id=retry_id,
            source_batch_id=digest(
                f"batch-{retry_id}"
            ),
            item_index=1,
            operation_id=digest(
                f"operation-{retry_id}"
            ),
            shopify_variant_id=(
                "gid://shopify/ProductVariant/"
                + variant_suffix
            ),
            shopify_sku=sku,
            before_quantity=before_quantity,
            requested_quantity=requested_quantity,
            inventory_delta=(
                requested_quantity
                - before_quantity
            ),
            attempt_number=3,
            event_type=event_type,
            error_message=(
                error_message
            ),
        )
    )


def build_services(
    connection_factory,
):
    dlq_repo = SupplierDeadLetterRepository(
        connection_factory=(
            connection_factory
        )
    )

    dlq_service = SupplierDeadLetterService(
        dlq_repo
    )

    resolution_repo = (
        SupplierCaseResolutionRepository(
            connection_factory=(
                connection_factory
            )
        )
    )

    resolution_service = (
        SupplierCaseResolutionService(
            resolution_repo
        )
    )

    workflow = SupplierOperatorWorkflow(
        dead_letter_repository=dlq_repo,
        dead_letter_service=dlq_service,
        resolution_repository=(
            resolution_repo
        ),
        resolution_service=(
            resolution_service
        ),
        allowed_sku_prefix="DLQ-DEMO-",
    )

    return (
        dlq_repo,
        dlq_service,
        resolution_repo,
        resolution_service,
        workflow,
    )


def seed_two_demo_cases(
    connection_factory,
):
    seed_terminal_retry(
        connection_factory=(
            connection_factory
        ),
        retry_id="a" * 64,
        sku="DLQ-DEMO-EXHAUSTED",
        variant_suffix="920001",
        event_type=(
            RetryEventType.RETRY_EXHAUSTED
        ),
    )

    seed_terminal_retry(
        connection_factory=(
            connection_factory
        ),
        retry_id="b" * 64,
        sku="DLQ-DEMO-NONRETRYABLE",
        variant_suffix="920002",
        event_type=(
            RetryEventType.RETRY_SKIPPED
        ),
        error_message=(
            "invalid credentials"
        ),
        before_quantity=6,
        requested_quantity=12,
    )

    (
        dlq_repo,
        dlq_service,
        resolution_repo,
        resolution_service,
        workflow,
    ) = build_services(
        connection_factory
    )

    dlq_service.scan_and_open_cases()

    cases = dlq_repo.get_cases(
        limit=10
    )

    exhausted = next(
        case
        for case in cases
        if (
            case.shopify_sku
            == "DLQ-DEMO-EXHAUSTED"
        )
    )

    dlq_service.acknowledge_case(
        case_id=(
            exhausted.case_id
        ),
        actor="Thomas",
        note="Investigating supplier failure",
    )

    return (
        dlq_repo,
        dlq_service,
        resolution_repo,
        resolution_service,
        workflow,
    )


def prepare(workflow):
    return workflow.prepare(
        actor="Thomas",
        acknowledgement_note=(
            "V2.7C synthetic acknowledgement."
        ),
        resolution_note=(
            "Synthetic validation case resolved."
        ),
        resolution_code=(
            ResolutionCode.OTHER
        ),
    )


def test_prepare_selects_two_unresolved_demo_cases():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    assert plan.case_count == 2


def test_prepare_orders_cases_deterministically():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    assert [
        case.shopify_sku
        for case in plan.cases
    ] == sorted(
        case.shopify_sku
        for case in plan.cases
    )


def test_prepare_identifies_only_awaiting_case_as_needing_ack():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    needs_ack = {
        case.shopify_sku:
            case.needs_acknowledgement
        for case in plan.cases
    }

    assert (
        needs_ack[
            "DLQ-DEMO-NONRETRYABLE"
        ]
        is True
    )
    assert (
        needs_ack[
            "DLQ-DEMO-EXHAUSTED"
        ]
        is False
    )


def test_prepare_ignores_non_demo_case():
    _, connection_factory = factory()

    seed_terminal_retry(
        connection_factory=(
            connection_factory
        ),
        retry_id="c" * 64,
        sku="REAL-SKU-DO-NOT-TOUCH",
        variant_suffix="930001",
        event_type=(
            RetryEventType.RETRY_EXHAUSTED
        ),
    )

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    assert all(
        case.shopify_sku.startswith(
            "DLQ-DEMO-"
        )
        for case in plan.cases
    )


def test_workflow_fingerprint_is_deterministic():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    first = prepare(
        workflow
    )
    second = prepare(
        workflow
    )

    assert (
        first.workflow_fingerprint
        == second.workflow_fingerprint
    )


def test_workflow_fingerprint_changes_with_note():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    first = prepare(
        workflow
    )

    second = workflow.prepare(
        actor="Thomas",
        acknowledgement_note=(
            "Different acknowledgement."
        ),
        resolution_note=(
            "Synthetic validation case resolved."
        ),
        resolution_code=(
            ResolutionCode.OTHER
        ),
    )

    assert (
        first.workflow_fingerprint
        != second.workflow_fingerprint
    )


def test_wrong_workflow_fingerprint_is_blocked():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    with pytest.raises(
        OperatorWorkflowError,
        match="does not match",
    ):
        workflow.execute(
            plan=plan,
            approved_workflow_fingerprint=(
                "f" * 64
            ),
            inventory_port=(
                FakeInventoryMutationAdapter()
            ),
        )


def test_execute_acknowledges_one_case():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    result = workflow.execute(
        plan=plan,
        approved_workflow_fingerprint=(
            plan.workflow_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    assert (
        result.acknowledgements_written
        == 1
    )


def test_execute_attempts_two_fake_recoveries():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    adapter = (
        FakeInventoryMutationAdapter()
    )

    result = workflow.execute(
        plan=plan,
        approved_workflow_fingerprint=(
            plan.workflow_fingerprint
        ),
        inventory_port=adapter,
    )

    assert (
        result.fake_recovery_attempts
        == 2
    )
    assert len(
        adapter.mutations
    ) == 2


def test_execute_closes_both_cases():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    result = workflow.execute(
        plan=plan,
        approved_workflow_fingerprint=(
            plan.workflow_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    assert result.cases_closed == 2
    assert result.succeeded is True


def test_execute_results_are_per_case():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    result = workflow.execute(
        plan=plan,
        approved_workflow_fingerprint=(
            plan.workflow_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    assert len(
        result.case_results
    ) == 2
    assert all(
        item.recovery_applied
        for item in result.case_results
    )
    assert all(
        item.case_closed
        for item in result.case_results
    )


def test_after_execution_prepare_is_empty():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    workflow.execute(
        plan=plan,
        approved_workflow_fingerprint=(
            plan.workflow_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    next_plan = prepare(
        workflow
    )

    assert next_plan.case_count == 0


def test_empty_plan_cannot_execute():
    _, connection_factory = factory()

    (
        dlq_repo,
        dlq_service,
        resolution_repo,
        resolution_service,
        workflow,
    ) = build_services(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    with pytest.raises(
        OperatorWorkflowError,
        match="no unresolved synthetic cases",
    ):
        workflow.execute(
            plan=plan,
            approved_workflow_fingerprint=(
                plan.workflow_fingerprint
            ),
            inventory_port=(
                FakeInventoryMutationAdapter()
            ),
        )


def test_resolution_events_are_written_for_both_cases():
    _, connection_factory = factory()

    (
        dlq_repo,
        dlq_service,
        resolution_repo,
        resolution_service,
        workflow,
    ) = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    workflow.execute(
        plan=plan,
        approved_workflow_fingerprint=(
            plan.workflow_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    closed_count = 0

    for case in dlq_repo.get_cases(
        limit=10
    ):
        if not case.shopify_sku.startswith(
            "DLQ-DEMO-"
        ):
            continue

        if (
            resolution_repo.get_event(
                case_id=(
                    case.case_id
                ),
                event_type=(
                    "case_closed"
                ),
            )
            is not None
        ):
            closed_count += 1

    assert closed_count == 2


def test_stale_plan_is_blocked_after_case_state_changes():
    _, connection_factory = factory()

    (
        dlq_repo,
        dlq_service,
        resolution_repo,
        resolution_service,
        workflow,
    ) = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    awaiting = next(
        case
        for case in dlq_repo.get_cases(
            limit=10
        )
        if case.status
        == "awaiting_human"
    )

    dlq_service.acknowledge_case(
        case_id=(
            awaiting.case_id
        ),
        actor="Thomas",
        note=(
            "V2.7C synthetic acknowledgement."
        ),
    )

    with pytest.raises(
        OperatorWorkflowError,
        match="stale",
    ):
        workflow.execute(
            plan=plan,
            approved_workflow_fingerprint=(
                plan.workflow_fingerprint
            ),
            inventory_port=(
                FakeInventoryMutationAdapter()
            ),
        )


def test_invalid_allowed_prefix_rejected():
    _, connection_factory = factory()

    (
        dlq_repo,
        dlq_service,
        resolution_repo,
        resolution_service,
        _,
    ) = build_services(
        connection_factory
    )

    with pytest.raises(
        OperatorWorkflowError,
        match="allowed_sku_prefix",
    ):
        SupplierOperatorWorkflow(
            dead_letter_repository=(
                dlq_repo
            ),
            dead_letter_service=(
                dlq_service
            ),
            resolution_repository=(
                resolution_repo
            ),
            resolution_service=(
                resolution_service
            ),
            allowed_sku_prefix="",
        )


def test_blank_actor_rejected():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    with pytest.raises(
        OperatorWorkflowError,
        match="actor",
    ):
        workflow.prepare(
            actor="",
            acknowledgement_note="A",
            resolution_note="B",
        )


def test_blank_resolution_note_rejected():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    with pytest.raises(
        OperatorWorkflowError,
        match="resolution_note",
    ):
        workflow.prepare(
            actor="Thomas",
            acknowledgement_note="A",
            resolution_note="",
        )


def test_fake_failure_does_not_report_success():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    failed_variant = (
        plan.cases[0]
        .shopify_variant_id
    )

    result = workflow.execute(
        plan=plan,
        approved_workflow_fingerprint=(
            plan.workflow_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter(
                fail_variant_ids={
                    failed_variant
                }
            )
        ),
    )

    assert result.succeeded is False
    assert result.cases_closed == 1
    assert (
        result.fake_recovery_successes
        == 1
    )


def test_failed_case_is_terminal_and_blocks_new_prepare():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    failed_variant = (
        plan.cases[0]
        .shopify_variant_id
    )

    workflow.execute(
        plan=plan,
        approved_workflow_fingerprint=(
            plan.workflow_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter(
                fail_variant_ids={
                    failed_variant
                }
            )
        ),
    )

    with pytest.raises(
        OperatorWorkflowError,
        match="failed controlled re-entry",
    ):
        prepare(
            workflow
        )


def test_only_synthetic_cases_are_mutated():
    _, connection_factory = factory()

    seed_terminal_retry(
        connection_factory=(
            connection_factory
        ),
        retry_id="c" * 64,
        sku="REAL-SKU-DO-NOT-TOUCH",
        variant_suffix="930001",
        event_type=(
            RetryEventType.RETRY_EXHAUSTED
        ),
    )

    (
        dlq_repo,
        dlq_service,
        resolution_repo,
        resolution_service,
        workflow,
    ) = seed_two_demo_cases(
        connection_factory
    )

    dlq_service.scan_and_open_cases()

    plan = prepare(
        workflow
    )

    adapter = (
        FakeInventoryMutationAdapter()
    )

    workflow.execute(
        plan=plan,
        approved_workflow_fingerprint=(
            plan.workflow_fingerprint
        ),
        inventory_port=adapter,
    )

    assert all(
        mutation.shopify_sku.startswith(
            "DLQ-DEMO-"
        )
        for mutation
        in adapter.mutations
    )


def test_workflow_preserves_original_requested_quantities():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    assert {
        case.requested_quantity
        for case in plan.cases
    } == {
        9,
        12,
    }


def test_workflow_plan_contains_resolution_code():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    assert (
        plan.resolution_code
        == ResolutionCode.OTHER
    )


def test_execution_preserves_workflow_fingerprint():
    _, connection_factory = factory()

    *_, workflow = seed_two_demo_cases(
        connection_factory
    )

    plan = prepare(
        workflow
    )

    result = workflow.execute(
        plan=plan,
        approved_workflow_fingerprint=(
            plan.workflow_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    assert (
        result.workflow_fingerprint
        == plan.workflow_fingerprint
    )
