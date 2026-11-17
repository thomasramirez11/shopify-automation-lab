import hashlib
import sqlite3
from contextlib import contextmanager

import pytest

from database.supplier_dead_letter_schema import (
    ensure_supplier_dead_letter_schema,
)
from supplier.batch.dead_letter_models import (
    DeadLetterAuditEvent,
    DeadLetterError,
    DeadLetterEventType,
    DeadLetterReason,
)
from supplier.batch.dead_letter_policy import (
    build_dead_letter_case_id,
)
from supplier.batch.dead_letter_repository import (
    SupplierDeadLetterRepository,
)
from supplier.batch.dead_letter_service import (
    SupplierDeadLetterService,
)
from supplier.batch.retry_models import (
    FailedBatchItem,
    RetryAuditEvent,
    RetryEventType,
)
from supplier.batch.retry_repository import (
    SupplierBatchRetryRepository,
)


VARIANT_A = "gid://shopify/ProductVariant/920001"
VARIANT_B = "gid://shopify/ProductVariant/920002"


def digest(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
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

    return connection, connection_factory


def retry_repo(
    connection_factory,
):
    return SupplierBatchRetryRepository(
        connection_factory=(
            connection_factory
        )
    )


def dlq_repo(
    connection_factory,
):
    return SupplierDeadLetterRepository(
        connection_factory=(
            connection_factory
        )
    )


def terminal_retry_event(
    *,
    retry_id,
    variant_id,
    sku,
    event_type,
    error_message=None,
):
    return RetryAuditEvent(
        retry_id=retry_id,
        source_batch_id=digest(
            f"batch-{retry_id}"
        ),
        item_index=1,
        operation_id=digest(
            f"operation-{retry_id}"
        ),
        shopify_variant_id=variant_id,
        shopify_sku=sku,
        before_quantity=4,
        requested_quantity=9,
        inventory_delta=5,
        attempt_number=3,
        event_type=event_type,
        error_message=error_message,
    )


def test_schema_creates_dead_letter_table():
    connection, _ = factory()

    ensure_supplier_dead_letter_schema(
        connection
    )

    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'supplier_dead_letter_events';
        """
    ).fetchone()

    assert row is not None


def test_schema_is_idempotent():
    connection, _ = factory()

    ensure_supplier_dead_letter_schema(
        connection
    )
    ensure_supplier_dead_letter_schema(
        connection
    )


def test_dead_letter_ledger_update_is_blocked():
    connection, connection_factory = factory()

    repository = dlq_repo(
        connection_factory
    )

    repository.append(
        DeadLetterAuditEvent(
            case_id="a" * 64,
            source_retry_id="b" * 64,
            source_batch_id="c" * 64,
            item_index=1,
            operation_id="d" * 64,
            shopify_variant_id=VARIANT_A,
            shopify_sku="SKU-A",
            requested_quantity=9,
            reason=(
                DeadLetterReason.RETRY_EXHAUSTED
            ),
            event_type=(
                DeadLetterEventType.CASE_OPENED
            ),
        )
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            UPDATE supplier_dead_letter_events
            SET requested_quantity = 999;
            """
        )


def test_dead_letter_ledger_delete_is_blocked():
    connection, connection_factory = factory()

    repository = dlq_repo(
        connection_factory
    )

    repository.append(
        DeadLetterAuditEvent(
            case_id="a" * 64,
            source_retry_id="b" * 64,
            source_batch_id="c" * 64,
            item_index=1,
            operation_id="d" * 64,
            shopify_variant_id=VARIANT_A,
            shopify_sku="SKU-A",
            requested_quantity=9,
            reason=(
                DeadLetterReason.RETRY_EXHAUSTED
            ),
            event_type=(
                DeadLetterEventType.CASE_OPENED
            ),
        )
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            DELETE FROM supplier_dead_letter_events;
            """
        )


def test_case_id_is_deterministic():
    candidate = FailedBatchItem(
        source_batch_id="a" * 64,
        item_index=1,
        operation_id="b" * 64,
        shopify_variant_id=VARIANT_A,
        shopify_sku="SKU-A",
        before_quantity=1,
        requested_quantity=2,
        inventory_delta=1,
        original_error_message="x",
    )

    # Use a small duck-typed candidate with the field policy needs.
    class Candidate:
        source_retry_id = "c" * 64

    assert (
        build_dead_letter_case_id(
            Candidate()
        )
        == build_dead_letter_case_id(
            Candidate()
        )
    )


def test_retry_exhausted_becomes_candidate():
    _, connection_factory = factory()

    retry_repository = retry_repo(
        connection_factory
    )

    retry_repository.append(
        terminal_retry_event(
            retry_id="a" * 64,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_EXHAUSTED
            ),
        )
    )

    candidates = (
        dlq_repo(
            connection_factory
        )
        .discover_escalation_candidates()
    )

    assert len(candidates) == 1
    assert (
        candidates[0].reason
        == DeadLetterReason.RETRY_EXHAUSTED
    )


def test_retry_skipped_becomes_non_retryable_candidate():
    _, connection_factory = factory()

    retry_repository = retry_repo(
        connection_factory
    )

    retry_repository.append(
        terminal_retry_event(
            retry_id="a" * 64,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_SKIPPED
            ),
            error_message="invalid credentials",
        )
    )

    candidates = (
        dlq_repo(
            connection_factory
        )
        .discover_escalation_candidates()
    )

    assert len(candidates) == 1
    assert (
        candidates[0].reason
        == (
            DeadLetterReason
            .NON_RETRYABLE_FAILURE
        )
    )


def test_recovered_retry_is_not_escalated():
    _, connection_factory = factory()

    retry_repository = retry_repo(
        connection_factory
    )

    retry_id = "a" * 64

    retry_repository.append(
        terminal_retry_event(
            retry_id=retry_id,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_EXHAUSTED
            ),
        )
    )

    retry_repository.append(
        RetryAuditEvent(
            retry_id=retry_id,
            source_batch_id=digest("batch-a"),
            item_index=1,
            operation_id=digest("operation-a"),
            shopify_variant_id=VARIANT_A,
            shopify_sku="SKU-A",
            before_quantity=4,
            requested_quantity=9,
            inventory_delta=5,
            attempt_number=4,
            event_type=(
                RetryEventType.RETRY_SUCCEEDED
            ),
        )
    )

    candidates = (
        dlq_repo(
            connection_factory
        )
        .discover_escalation_candidates()
    )

    assert candidates == []


def test_scan_opens_exhausted_case():
    _, connection_factory = factory()

    retry_repo(
        connection_factory
    ).append(
        terminal_retry_event(
            retry_id="a" * 64,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_EXHAUSTED
            ),
        )
    )

    repository = dlq_repo(
        connection_factory
    )
    service = SupplierDeadLetterService(
        repository
    )

    summary = (
        service.scan_and_open_cases()
    )

    assert summary.cases_opened == 1
    assert repository.count_events() == 1


def test_scan_opens_non_retryable_case():
    _, connection_factory = factory()

    retry_repo(
        connection_factory
    ).append(
        terminal_retry_event(
            retry_id="a" * 64,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_SKIPPED
            ),
            error_message="invalid credentials",
        )
    )

    repository = dlq_repo(
        connection_factory
    )
    service = SupplierDeadLetterService(
        repository
    )

    summary = (
        service.scan_and_open_cases()
    )

    assert summary.cases_opened == 1
    assert (
        repository.get_cases(
            limit=1
        )[0].reason_code
        == "non_retryable_failure"
    )


def test_scan_is_idempotent():
    _, connection_factory = factory()

    retry_repo(
        connection_factory
    ).append(
        terminal_retry_event(
            retry_id="a" * 64,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_EXHAUSTED
            ),
        )
    )

    repository = dlq_repo(
        connection_factory
    )
    service = SupplierDeadLetterService(
        repository
    )

    first = service.scan_and_open_cases()
    second = service.scan_and_open_cases()

    assert first.cases_opened == 1
    assert second.cases_opened == 0
    assert second.already_open == 1
    assert repository.count_events() == 1


def test_two_terminal_retries_open_two_cases():
    _, connection_factory = factory()

    retry_repository = retry_repo(
        connection_factory
    )

    retry_repository.append(
        terminal_retry_event(
            retry_id="a" * 64,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_EXHAUSTED
            ),
        )
    )

    retry_repository.append(
        terminal_retry_event(
            retry_id="b" * 64,
            variant_id=VARIANT_B,
            sku="SKU-B",
            event_type=(
                RetryEventType.RETRY_SKIPPED
            ),
            error_message="invalid credentials",
        )
    )

    repository = dlq_repo(
        connection_factory
    )

    summary = (
        SupplierDeadLetterService(
            repository
        )
        .scan_and_open_cases()
    )

    assert summary.escalation_candidates_seen == 2
    assert summary.cases_opened == 2


def test_case_starts_awaiting_human():
    _, connection_factory = factory()

    retry_repo(
        connection_factory
    ).append(
        terminal_retry_event(
            retry_id="a" * 64,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_EXHAUSTED
            ),
        )
    )

    repository = dlq_repo(
        connection_factory
    )

    SupplierDeadLetterService(
        repository
    ).scan_and_open_cases()

    case = repository.get_cases(
        limit=1
    )[0]

    assert case.status == "awaiting_human"
    assert case.acknowledged_by is None


def test_acknowledge_case_records_human_owner():
    _, connection_factory = factory()

    retry_repo(
        connection_factory
    ).append(
        terminal_retry_event(
            retry_id="a" * 64,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_EXHAUSTED
            ),
        )
    )

    repository = dlq_repo(
        connection_factory
    )
    service = SupplierDeadLetterService(
        repository
    )

    service.scan_and_open_cases()

    case_id = repository.get_cases(
        limit=1
    )[0].case_id

    service.acknowledge_case(
        case_id=case_id,
        actor="Thomas",
        note="Investigating supplier response.",
    )

    case = repository.get_cases(
        limit=1
    )[0]

    assert case.status == "acknowledged"
    assert case.acknowledged_by == "Thomas"
    assert (
        case.acknowledgement_note
        == "Investigating supplier response."
    )


def test_acknowledge_unknown_case_is_rejected():
    _, connection_factory = factory()

    service = SupplierDeadLetterService(
        dlq_repo(
            connection_factory
        )
    )

    with pytest.raises(
        DeadLetterError,
        match="unknown",
    ):
        service.acknowledge_case(
            case_id="a" * 64,
            actor="Thomas",
            note="Reviewing.",
        )


def test_acknowledge_requires_actor():
    with pytest.raises(
        DeadLetterError,
        match="actor",
    ):
        DeadLetterAuditEvent(
            case_id="a" * 64,
            source_retry_id="b" * 64,
            source_batch_id="c" * 64,
            item_index=1,
            operation_id="d" * 64,
            shopify_variant_id=VARIANT_A,
            shopify_sku="SKU-A",
            requested_quantity=9,
            reason=(
                DeadLetterReason.RETRY_EXHAUSTED
            ),
            event_type=(
                DeadLetterEventType
                .CASE_ACKNOWLEDGED
            ),
            actor="",
            note="Reviewing.",
        )


def test_acknowledge_requires_note():
    with pytest.raises(
        DeadLetterError,
        match="note",
    ):
        DeadLetterAuditEvent(
            case_id="a" * 64,
            source_retry_id="b" * 64,
            source_batch_id="c" * 64,
            item_index=1,
            operation_id="d" * 64,
            shopify_variant_id=VARIANT_A,
            shopify_sku="SKU-A",
            requested_quantity=9,
            reason=(
                DeadLetterReason.RETRY_EXHAUSTED
            ),
            event_type=(
                DeadLetterEventType
                .CASE_ACKNOWLEDGED
            ),
            actor="Thomas",
            note="",
        )


def test_same_acknowledgement_is_idempotent():
    _, connection_factory = factory()

    retry_repo(
        connection_factory
    ).append(
        terminal_retry_event(
            retry_id="a" * 64,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_EXHAUSTED
            ),
        )
    )

    repository = dlq_repo(
        connection_factory
    )
    service = SupplierDeadLetterService(
        repository
    )

    service.scan_and_open_cases()

    case_id = repository.get_cases(
        limit=1
    )[0].case_id

    first = service.acknowledge_case(
        case_id=case_id,
        actor="Thomas",
        note="Investigating.",
    )

    second = service.acknowledge_case(
        case_id=case_id,
        actor="Thomas",
        note="Investigating.",
    )

    assert (
        first.dead_letter_event_id
        == second.dead_letter_event_id
    )
    assert repository.count_events() == 2


def test_conflicting_second_acknowledgement_is_rejected():
    _, connection_factory = factory()

    retry_repo(
        connection_factory
    ).append(
        terminal_retry_event(
            retry_id="a" * 64,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_EXHAUSTED
            ),
        )
    )

    repository = dlq_repo(
        connection_factory
    )
    service = SupplierDeadLetterService(
        repository
    )

    service.scan_and_open_cases()

    case_id = repository.get_cases(
        limit=1
    )[0].case_id

    service.acknowledge_case(
        case_id=case_id,
        actor="Thomas",
        note="Investigating.",
    )

    with pytest.raises(
        DeadLetterError,
        match="different details",
    ):
        service.acknowledge_case(
            case_id=case_id,
            actor="SomeoneElse",
            note="Changed note.",
        )


def test_case_events_preserve_open_then_ack_order():
    _, connection_factory = factory()

    retry_repo(
        connection_factory
    ).append(
        terminal_retry_event(
            retry_id="a" * 64,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_EXHAUSTED
            ),
        )
    )

    repository = dlq_repo(
        connection_factory
    )
    service = SupplierDeadLetterService(
        repository
    )

    service.scan_and_open_cases()

    case_id = repository.get_cases(
        limit=1
    )[0].case_id

    service.acknowledge_case(
        case_id=case_id,
        actor="Thomas",
        note="Investigating.",
    )

    events = repository.get_case_events(
        case_id
    )

    assert [
        event.event_type
        for event in events
    ] == [
        "case_opened",
        "case_acknowledged",
    ]


def test_get_cases_limit_validation():
    _, connection_factory = factory()

    repository = dlq_repo(
        connection_factory
    )

    with pytest.raises(
        ValueError,
        match="positive integer",
    ):
        repository.get_cases(
            limit=0
        )


def test_invalid_case_id_is_rejected():
    with pytest.raises(
        DeadLetterError,
        match="64-character",
    ):
        DeadLetterAuditEvent(
            case_id="bad",
            source_retry_id="b" * 64,
            source_batch_id="c" * 64,
            item_index=1,
            operation_id="d" * 64,
            shopify_variant_id=VARIANT_A,
            shopify_sku="SKU-A",
            requested_quantity=9,
            reason=(
                DeadLetterReason.RETRY_EXHAUSTED
            ),
            event_type=(
                DeadLetterEventType.CASE_OPENED
            ),
        )


def test_negative_requested_quantity_is_rejected():
    with pytest.raises(
        DeadLetterError,
        match="cannot be negative",
    ):
        DeadLetterAuditEvent(
            case_id="a" * 64,
            source_retry_id="b" * 64,
            source_batch_id="c" * 64,
            item_index=1,
            operation_id="d" * 64,
            shopify_variant_id=VARIANT_A,
            shopify_sku="SKU-A",
            requested_quantity=-1,
            reason=(
                DeadLetterReason.RETRY_EXHAUSTED
            ),
            event_type=(
                DeadLetterEventType.CASE_OPENED
            ),
        )


def test_dead_letter_case_keeps_source_retry_identity():
    _, connection_factory = factory()

    source_retry_id = "a" * 64

    retry_repo(
        connection_factory
    ).append(
        terminal_retry_event(
            retry_id=source_retry_id,
            variant_id=VARIANT_A,
            sku="SKU-A",
            event_type=(
                RetryEventType.RETRY_EXHAUSTED
            ),
        )
    )

    repository = dlq_repo(
        connection_factory
    )

    SupplierDeadLetterService(
        repository
    ).scan_and_open_cases()

    case = repository.get_cases(
        limit=1
    )[0]

    assert (
        case.source_retry_id
        == source_retry_id
    )
