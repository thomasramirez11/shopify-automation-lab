import sqlite3
from contextlib import contextmanager
from dataclasses import replace

import pytest

from database.supplier_execution_schema import (
    ensure_supplier_execution_schema,
)
from supplier.audit.models import (
    SupplierExecutionAuditError,
    SupplierExecutionAuditEvent,
    SupplierExecutionEventType,
)
from supplier.audit.repository import (
    SupplierExecutionAuditRepository,
)
from supplier.audit.service import (
    SupplierExecutionAuditService,
)
from supplier.decision.models import (
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.plan.builder import (
    build_dry_run_sync_plan,
)


VARIANT_ID = "gid://shopify/ProductVariant/111"
INVENTORY_ITEM_ID = "gid://shopify/InventoryItem/222"
LOCATION_ID = "gid://shopify/Location/333"
FINGERPRINT = "a" * 64
OPERATION_ID = "11111111-2222-3333-4444-555555555555"


def make_connection_factory():
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


def event(
    *,
    event_type=(
        SupplierExecutionEventType
        .EXECUTION_STARTED
    ),
    observed_after=None,
    error_message=None,
):
    return SupplierExecutionAuditEvent(
        operation_id=OPERATION_ID,
        event_type=event_type,
        supplier_code="demo_supplier",
        supplier_sku="SUP-CAP-001",
        shopify_variant_id=VARIANT_ID,
        shopify_sku="AUTO-Cap-001",
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
        before_quantity=1,
        requested_quantity=25,
        observed_after_quantity=observed_after,
        inventory_delta=24,
        plan_fingerprint=FINGERPRINT,
        idempotency_key=OPERATION_ID,
        error_message=error_message,
    )


def eligible_plan():
    decision = SupplierSyncDecision(
        supplier_code="demo_supplier",
        supplier_sku="SUP-CAP-001",
        shopify_variant_id=VARIANT_ID,
        shopify_sku="AUTO-Cap-001",
        status=SyncDecisionStatus.ELIGIBLE,
        reason=(
            SyncDecisionReason
            .INVENTORY_MISMATCH_WITHIN_LIMIT
        ),
        current_inventory_quantity=1,
        supplier_inventory_quantity=25,
        inventory_delta=24,
        proposed_inventory_quantity=25,
    )

    return build_dry_run_sync_plan(
        [
            decision
        ]
    )


def test_schema_creates_event_table():
    connection, _ = (
        make_connection_factory()
    )

    ensure_supplier_execution_schema(
        connection
    )

    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'supplier_execution_events';
        """
    ).fetchone()

    assert row is not None


def test_schema_is_idempotent():
    connection, _ = (
        make_connection_factory()
    )

    ensure_supplier_execution_schema(
        connection
    )
    ensure_supplier_execution_schema(
        connection
    )

    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'supplier_execution_events';
        """
    ).fetchone()

    assert row["count"] == 1


def test_repository_appends_started_event():
    _, factory = (
        make_connection_factory()
    )

    repository = (
        SupplierExecutionAuditRepository(
            connection_factory=factory
        )
    )

    result = repository.append(
        event()
    )

    assert result.created_new is True
    assert result.event_id == 1
    assert repository.count_events() == 1


def test_repeated_same_event_is_idempotent():
    _, factory = (
        make_connection_factory()
    )

    repository = (
        SupplierExecutionAuditRepository(
            connection_factory=factory
        )
    )

    first = repository.append(
        event()
    )
    second = repository.append(
        event()
    )

    assert first.event_id == second.event_id
    assert second.created_new is False
    assert repository.count_events() == 1


def test_same_operation_can_store_verified_event():
    _, factory = (
        make_connection_factory()
    )

    repository = (
        SupplierExecutionAuditRepository(
            connection_factory=factory
        )
    )

    repository.append(
        event()
    )
    repository.append(
        event(
            event_type=(
                SupplierExecutionEventType
                .EXECUTION_VERIFIED
            ),
            observed_after=25,
        )
    )

    events = repository.get_operation_events(
        OPERATION_ID
    )

    assert len(events) == 2
    assert (
        events[1].event_type
        == "execution_verified"
    )
    assert (
        events[1]
        .observed_after_quantity
        == 25
    )


def test_failed_event_requires_error_message():
    with pytest.raises(
        SupplierExecutionAuditError,
        match="requires error_message",
    ):
        event(
            event_type=(
                SupplierExecutionEventType
                .EXECUTION_FAILED
            )
        )


def test_verified_event_requires_after_quantity():
    with pytest.raises(
        SupplierExecutionAuditError,
        match="requires observed_after_quantity",
    ):
        event(
            event_type=(
                SupplierExecutionEventType
                .EXECUTION_VERIFIED
            )
        )


def test_invalid_fingerprint_is_rejected():
    with pytest.raises(
        SupplierExecutionAuditError,
        match="64-character",
    ):
        replace(
            event(),
            plan_fingerprint="bad",
        )


def test_negative_quantity_is_rejected():
    with pytest.raises(
        SupplierExecutionAuditError,
        match="cannot be negative",
    ):
        replace(
            event(),
            before_quantity=-1,
        )


def test_ledger_blocks_update():
    connection, factory = (
        make_connection_factory()
    )

    repository = (
        SupplierExecutionAuditRepository(
            connection_factory=factory
        )
    )
    repository.append(
        event()
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            UPDATE supplier_execution_events
            SET requested_quantity = 99
            WHERE event_id = 1;
            """
        )


def test_ledger_blocks_delete():
    connection, factory = (
        make_connection_factory()
    )

    repository = (
        SupplierExecutionAuditRepository(
            connection_factory=factory
        )
    )
    repository.append(
        event()
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            DELETE FROM supplier_execution_events
            WHERE event_id = 1;
            """
        )


def test_recent_events_returns_newest_first():
    _, factory = (
        make_connection_factory()
    )

    repository = (
        SupplierExecutionAuditRepository(
            connection_factory=factory
        )
    )

    repository.append(
        event()
    )
    repository.append(
        event(
            event_type=(
                SupplierExecutionEventType
                .EXECUTION_VERIFIED
            ),
            observed_after=25,
        )
    )

    recent = repository.get_recent(
        limit=2
    )

    assert (
        recent[0].event_type
        == "execution_verified"
    )
    assert (
        recent[1].event_type
        == "execution_started"
    )


def test_recent_events_rejects_bad_limit():
    _, factory = (
        make_connection_factory()
    )

    repository = (
        SupplierExecutionAuditRepository(
            connection_factory=factory
        )
    )

    with pytest.raises(
        ValueError,
        match="positive integer",
    ):
        repository.get_recent(
            limit=0
        )


def test_service_operation_id_is_deterministic():
    _, factory = (
        make_connection_factory()
    )

    service = (
        SupplierExecutionAuditService(
            SupplierExecutionAuditRepository(
                connection_factory=factory
            )
        )
    )

    plan = eligible_plan()

    first = service.operation_id_for(
        plan=plan,
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
    )

    second = service.operation_id_for(
        plan=plan,
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
    )

    assert first == second


def test_service_records_started_and_verified():
    _, factory = (
        make_connection_factory()
    )

    repository = (
        SupplierExecutionAuditRepository(
            connection_factory=factory
        )
    )

    service = (
        SupplierExecutionAuditService(
            repository
        )
    )

    plan = eligible_plan()

    service.record_started(
        plan=plan,
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
    )

    service.record_verified(
        plan=plan,
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
        observed_after_quantity=25,
    )

    assert repository.count_events() == 2


def test_service_records_failure():
    _, factory = (
        make_connection_factory()
    )

    repository = (
        SupplierExecutionAuditRepository(
            connection_factory=factory
        )
    )

    service = (
        SupplierExecutionAuditService(
            repository
        )
    )

    plan = eligible_plan()

    service.record_started(
        plan=plan,
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
    )

    service.record_failed(
        plan=plan,
        inventory_item_id=INVENTORY_ITEM_ID,
        location_id=LOCATION_ID,
        error_message=(
            "Shopify rejected mutation."
        ),
    )

    events = repository.get_recent(
        limit=2
    )

    assert (
        events[0].event_type
        == "execution_failed"
    )
    assert (
        events[0].error_message
        == "Shopify rejected mutation."
    )


def test_service_rejects_multi_item_plan():
    _, factory = (
        make_connection_factory()
    )

    service = (
        SupplierExecutionAuditService(
            SupplierExecutionAuditRepository(
                connection_factory=factory
            )
        )
    )

    first = SupplierSyncDecision(
        supplier_code="demo_supplier",
        supplier_sku="SUP-CAP-001",
        shopify_variant_id=VARIANT_ID,
        shopify_sku="AUTO-Cap-001",
        status=SyncDecisionStatus.ELIGIBLE,
        reason=(
            SyncDecisionReason
            .INVENTORY_MISMATCH_WITHIN_LIMIT
        ),
        current_inventory_quantity=1,
        supplier_inventory_quantity=25,
        inventory_delta=24,
        proposed_inventory_quantity=25,
    )

    second = SupplierSyncDecision(
        supplier_code="demo_supplier",
        supplier_sku="SUP-SHIRT-L",
        shopify_variant_id=(
            "gid://shopify/ProductVariant/999"
        ),
        shopify_sku="AUTO-shirt-L",
        status=SyncDecisionStatus.ELIGIBLE,
        reason=(
            SyncDecisionReason
            .INVENTORY_MISMATCH_WITHIN_LIMIT
        ),
        current_inventory_quantity=2,
        supplier_inventory_quantity=40,
        inventory_delta=38,
        proposed_inventory_quantity=40,
    )

    multi = build_dry_run_sync_plan(
        [
            first,
            second,
        ]
    )

    with pytest.raises(
        ValueError,
        match="exactly one",
    ):
        service.operation_id_for(
            plan=multi,
            inventory_item_id=INVENTORY_ITEM_ID,
            location_id=LOCATION_ID,
        )
