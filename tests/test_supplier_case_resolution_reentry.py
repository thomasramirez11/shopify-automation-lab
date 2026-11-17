import hashlib
import sqlite3
from contextlib import contextmanager

import pytest

from database.supplier_case_resolution_schema import (
    ensure_supplier_case_resolution_schema,
)
from supplier.batch.case_resolution_models import (
    CaseResolutionError,
    CaseResolutionEvent,
    ResolutionCode,
    ResolutionEventType,
)
from supplier.batch.case_resolution_policy import (
    build_resolution_fingerprint,
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


VARIANT = "gid://shopify/ProductVariant/930001"
SKU = "REENTRY-SKU"


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


def seed_acknowledged_case(
    connection_factory,
):
    retry_repository = (
        SupplierBatchRetryRepository(
            connection_factory=(
                connection_factory
            )
        )
    )

    retry_repository.append(
        RetryAuditEvent(
            retry_id=digest("retry"),
            source_batch_id=digest("batch"),
            item_index=1,
            operation_id=digest("operation"),
            shopify_variant_id=VARIANT,
            shopify_sku=SKU,
            before_quantity=3,
            requested_quantity=14,
            inventory_delta=11,
            attempt_number=3,
            event_type=(
                RetryEventType
                .RETRY_EXHAUSTED
            ),
        )
    )

    dlq_repository = (
        SupplierDeadLetterRepository(
            connection_factory=(
                connection_factory
            )
        )
    )

    dlq_service = (
        SupplierDeadLetterService(
            dlq_repository
        )
    )

    dlq_service.scan_and_open_cases()

    case = dlq_repository.get_cases(
        limit=1
    )[0]

    dlq_service.acknowledge_case(
        case_id=case.case_id,
        actor="Thomas",
        note="Investigating.",
    )

    return case.case_id


def repository(
    connection_factory,
):
    return SupplierCaseResolutionRepository(
        connection_factory=(
            connection_factory
        )
    )


def service(
    connection_factory,
):
    repo = repository(
        connection_factory
    )
    return (
        repo,
        SupplierCaseResolutionService(
            repo
        ),
    )


def record_resolution(
    connection_factory,
):
    case_id = seed_acknowledged_case(
        connection_factory
    )

    repo, svc = service(
        connection_factory
    )

    resolution = svc.record_resolution(
        case_id=case_id,
        resolution_code=(
            ResolutionCode.SUPPLIER_FIXED
        ),
        actor="Thomas",
        note="Supplier issue fixed.",
    )

    return (
        case_id,
        repo,
        svc,
        resolution,
    )


def test_schema_creates_resolution_table():
    connection, _ = factory()

    ensure_supplier_case_resolution_schema(
        connection
    )

    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'supplier_case_resolution_events';
        """
    ).fetchone()

    assert row is not None


def test_schema_is_idempotent():
    connection, _ = factory()

    ensure_supplier_case_resolution_schema(
        connection
    )
    ensure_supplier_case_resolution_schema(
        connection
    )


def test_resolution_ledger_update_is_blocked():
    connection, connection_factory = factory()

    case_id, repo, _, resolution = (
        record_resolution(
            connection_factory
        )
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            UPDATE supplier_case_resolution_events
            SET requested_quantity = 999;
            """
        )


def test_resolution_ledger_delete_is_blocked():
    connection, connection_factory = factory()

    record_resolution(
        connection_factory
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            DELETE FROM supplier_case_resolution_events;
            """
        )


def test_unacknowledged_case_cannot_be_resolved():
    _, connection_factory = factory()

    retry_repository = (
        SupplierBatchRetryRepository(
            connection_factory=(
                connection_factory
            )
        )
    )

    retry_repository.append(
        RetryAuditEvent(
            retry_id=digest("retry-x"),
            source_batch_id=digest("batch-x"),
            item_index=1,
            operation_id=digest("operation-x"),
            shopify_variant_id=VARIANT,
            shopify_sku=SKU,
            before_quantity=1,
            requested_quantity=2,
            inventory_delta=1,
            attempt_number=3,
            event_type=(
                RetryEventType
                .RETRY_EXHAUSTED
            ),
        )
    )

    dlq_repository = (
        SupplierDeadLetterRepository(
            connection_factory=(
                connection_factory
            )
        )
    )

    SupplierDeadLetterService(
        dlq_repository
    ).scan_and_open_cases()

    case_id = dlq_repository.get_cases(
        limit=1
    )[0].case_id

    _, svc = service(
        connection_factory
    )

    with pytest.raises(
        CaseResolutionError,
        match="acknowledged",
    ):
        svc.record_resolution(
            case_id=case_id,
            resolution_code=(
                ResolutionCode.SUPPLIER_FIXED
            ),
            actor="Thomas",
            note="Fixed.",
        )


def test_resolution_fingerprint_is_deterministic():
    _, connection_factory = factory()

    case_id = seed_acknowledged_case(
        connection_factory
    )

    repo, _ = service(
        connection_factory
    )

    case = repo.get_acknowledged_case(
        case_id
    )

    first = build_resolution_fingerprint(
        case=case,
        resolution_code=(
            ResolutionCode.SUPPLIER_FIXED
        ),
        actor="Thomas",
        note="Fixed.",
    )

    second = build_resolution_fingerprint(
        case=case,
        resolution_code=(
            ResolutionCode.SUPPLIER_FIXED
        ),
        actor="Thomas",
        note="Fixed.",
    )

    assert first == second


def test_resolution_fingerprint_changes_with_note():
    _, connection_factory = factory()

    case_id = seed_acknowledged_case(
        connection_factory
    )

    repo, _ = service(
        connection_factory
    )

    case = repo.get_acknowledged_case(
        case_id
    )

    first = build_resolution_fingerprint(
        case=case,
        resolution_code=(
            ResolutionCode.SUPPLIER_FIXED
        ),
        actor="Thomas",
        note="Fixed A.",
    )

    second = build_resolution_fingerprint(
        case=case,
        resolution_code=(
            ResolutionCode.SUPPLIER_FIXED
        ),
        actor="Thomas",
        note="Fixed B.",
    )

    assert first != second


def test_resolution_fingerprint_changes_with_code():
    _, connection_factory = factory()

    case_id = seed_acknowledged_case(
        connection_factory
    )

    repo, _ = service(
        connection_factory
    )
    case = repo.get_acknowledged_case(
        case_id
    )

    first = build_resolution_fingerprint(
        case=case,
        resolution_code=(
            ResolutionCode.SUPPLIER_FIXED
        ),
        actor="Thomas",
        note="Fixed.",
    )

    second = build_resolution_fingerprint(
        case=case,
        resolution_code=(
            ResolutionCode.CONFIGURATION_FIXED
        ),
        actor="Thomas",
        note="Fixed.",
    )

    assert first != second


def test_record_resolution_adds_one_event():
    _, connection_factory = factory()

    _, repo, _, _ = record_resolution(
        connection_factory
    )

    assert repo.count_events() == 1


def test_record_resolution_is_idempotent():
    _, connection_factory = factory()

    case_id, repo, svc, first = (
        record_resolution(
            connection_factory
        )
    )

    second = svc.record_resolution(
        case_id=case_id,
        resolution_code=(
            ResolutionCode.SUPPLIER_FIXED
        ),
        actor="Thomas",
        note="Supplier issue fixed.",
    )

    assert (
        first.resolution_fingerprint
        == second.resolution_fingerprint
    )
    assert repo.count_events() == 1


def test_conflicting_resolution_is_rejected():
    _, connection_factory = factory()

    case_id, _, svc, _ = (
        record_resolution(
            connection_factory
        )
    )

    with pytest.raises(
        CaseResolutionError,
        match="different recorded resolution",
    ):
        svc.record_resolution(
            case_id=case_id,
            resolution_code=(
                ResolutionCode.CONFIGURATION_FIXED
            ),
            actor="Thomas",
            note="Different resolution.",
        )


def test_authorize_requires_recorded_resolution():
    _, connection_factory = factory()

    case_id = seed_acknowledged_case(
        connection_factory
    )

    _, svc = service(
        connection_factory
    )

    with pytest.raises(
        CaseResolutionError,
        match="recorded",
    ):
        svc.authorize_reentry(
            case_id=case_id,
            approved_resolution_fingerprint=(
                "a" * 64
            ),
        )


def test_wrong_fingerprint_blocks_authorization():
    _, connection_factory = factory()

    case_id, _, svc, _ = (
        record_resolution(
            connection_factory
        )
    )

    with pytest.raises(
        CaseResolutionError,
        match="does not match",
    ):
        svc.authorize_reentry(
            case_id=case_id,
            approved_resolution_fingerprint=(
                "f" * 64
            ),
        )


def test_correct_fingerprint_authorizes_reentry():
    _, connection_factory = factory()

    case_id, repo, svc, resolution = (
        record_resolution(
            connection_factory
        )
    )

    event = svc.authorize_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
    )

    assert (
        event.event_type
        == "reentry_authorized"
    )
    assert repo.count_events() == 2


def test_authorization_is_idempotent():
    _, connection_factory = factory()

    case_id, repo, svc, resolution = (
        record_resolution(
            connection_factory
        )
    )

    first = svc.authorize_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
    )

    second = svc.authorize_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
    )

    assert (
        first.resolution_event_id
        == second.resolution_event_id
    )
    assert repo.count_events() == 2


def test_successful_reentry_attempts_one_item_only():
    _, connection_factory = factory()

    case_id, _, svc, resolution = (
        record_resolution(
            connection_factory
        )
    )

    adapter = (
        FakeInventoryMutationAdapter()
    )

    result = svc.execute_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
        inventory_port=adapter,
    )

    assert result.attempted is True
    assert result.applied is True
    assert len(adapter.mutations) == 1
    assert (
        adapter.mutations[0].shopify_sku
        == SKU
    )


def test_successful_reentry_closes_case():
    _, connection_factory = factory()

    case_id, repo, svc, resolution = (
        record_resolution(
            connection_factory
        )
    )

    result = svc.execute_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    assert result.closed is True

    event_types = [
        event.event_type
        for event in repo.get_events(
            case_id
        )
    ]

    assert event_types == [
        "resolution_recorded",
        "reentry_authorized",
        "reentry_started",
        "reentry_succeeded",
        "case_closed",
    ]


def test_failed_reentry_does_not_close_case():
    _, connection_factory = factory()

    case_id, repo, svc, resolution = (
        record_resolution(
            connection_factory
        )
    )

    result = svc.execute_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter(
                fail_variant_ids={
                    VARIANT
                }
            )
        ),
    )

    assert result.applied is False
    assert result.closed is False

    event_types = [
        event.event_type
        for event in repo.get_events(
            case_id
        )
    ]

    assert event_types[-1] == "reentry_failed"
    assert "case_closed" not in event_types


def test_failed_reentry_records_error():
    _, connection_factory = factory()

    case_id, repo, svc, resolution = (
        record_resolution(
            connection_factory
        )
    )

    svc.execute_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter(
                fail_variant_ids={
                    VARIANT
                }
            )
        ),
    )

    failed = repo.get_event(
        case_id=case_id,
        event_type="reentry_failed",
    )

    assert "applied=False" in failed.error_message


def test_second_reentry_after_success_is_blocked():
    _, connection_factory = factory()

    case_id, _, svc, resolution = (
        record_resolution(
            connection_factory
        )
    )

    svc.execute_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    with pytest.raises(
        CaseResolutionError,
        match="terminal outcome",
    ):
        svc.execute_reentry(
            case_id=case_id,
            approved_resolution_fingerprint=(
                resolution
                .resolution_fingerprint
            ),
            inventory_port=(
                FakeInventoryMutationAdapter()
            ),
        )


def test_second_reentry_after_failure_is_blocked():
    _, connection_factory = factory()

    case_id, _, svc, resolution = (
        record_resolution(
            connection_factory
        )
    )

    svc.execute_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter(
                fail_variant_ids={
                    VARIANT
                }
            )
        ),
    )

    with pytest.raises(
        CaseResolutionError,
        match="terminal outcome",
    ):
        svc.execute_reentry(
            case_id=case_id,
            approved_resolution_fingerprint=(
                resolution
                .resolution_fingerprint
            ),
            inventory_port=(
                FakeInventoryMutationAdapter()
            ),
        )


def test_case_view_reports_closed():
    _, connection_factory = factory()

    case_id, repo, svc, resolution = (
        record_resolution(
            connection_factory
        )
    )

    svc.execute_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    view = repo.get_cases(
        limit=1
    )[0]

    assert view.status == "closed"


def test_case_view_reports_reentry_failed():
    _, connection_factory = factory()

    case_id, repo, svc, resolution = (
        record_resolution(
            connection_factory
        )
    )

    svc.execute_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter(
                fail_variant_ids={
                    VARIANT
                }
            )
        ),
    )

    view = repo.get_cases(
        limit=1
    )[0]

    assert view.status == "reentry_failed"
    assert "applied=False" in view.error_message


def test_case_view_reports_resolution_recorded_before_authorization():
    _, connection_factory = factory()

    _, repo, _, _ = record_resolution(
        connection_factory
    )

    view = repo.get_cases(
        limit=1
    )[0]

    assert (
        view.status
        == "resolution_recorded"
    )


def test_get_cases_limit_validation():
    _, connection_factory = factory()

    repo = repository(
        connection_factory
    )

    with pytest.raises(
        ValueError,
        match="positive integer",
    ):
        repo.get_cases(
            limit=0
        )


def test_reentry_failed_requires_error_message():
    with pytest.raises(
        CaseResolutionError,
        match="requires error_message",
    ):
        CaseResolutionEvent(
            case_id="a" * 64,
            resolution_fingerprint="b" * 64,
            event_type=(
                ResolutionEventType
                .REENTRY_FAILED
            ),
            resolution_code=(
                ResolutionCode.OTHER
            ),
            actor="Thomas",
            note="Testing.",
            shopify_variant_id=VARIANT,
            shopify_sku=SKU,
            requested_quantity=1,
        )


def test_negative_requested_quantity_is_rejected():
    with pytest.raises(
        CaseResolutionError,
        match="cannot be negative",
    ):
        CaseResolutionEvent(
            case_id="a" * 64,
            resolution_fingerprint="b" * 64,
            event_type=(
                ResolutionEventType
                .RESOLUTION_RECORDED
            ),
            resolution_code=(
                ResolutionCode.OTHER
            ),
            actor="Thomas",
            note="Testing.",
            shopify_variant_id=VARIANT,
            shopify_sku=SKU,
            requested_quantity=-1,
        )


def test_resolution_preserves_original_requested_quantity():
    _, connection_factory = factory()

    _, _, _, resolution = (
        record_resolution(
            connection_factory
        )
    )

    assert (
        resolution.requested_quantity
        == 14
    )


def test_reentry_result_preserves_fingerprint():
    _, connection_factory = factory()

    case_id, _, svc, resolution = (
        record_resolution(
            connection_factory
        )
    )

    result = svc.execute_reentry(
        case_id=case_id,
        approved_resolution_fingerprint=(
            resolution
            .resolution_fingerprint
        ),
        inventory_port=(
            FakeInventoryMutationAdapter()
        ),
    )

    assert (
        result.resolution_fingerprint
        == resolution
        .resolution_fingerprint
    )
