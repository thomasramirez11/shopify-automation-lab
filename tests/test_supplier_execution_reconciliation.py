import sqlite3
from contextlib import contextmanager

import pytest

from database.supplier_execution_schema import (
    ensure_supplier_execution_schema,
)
from database.supplier_reconciliation_schema import (
    ensure_supplier_reconciliation_schema,
)
from supplier.audit.models import (
    SupplierExecutionAuditEvent,
    SupplierExecutionEventType,
)
from supplier.audit.repository import (
    SupplierExecutionAuditRepository,
)
from supplier.reconciliation.models import (
    ReconciliationObservation,
    ReconciliationStatus,
)
from supplier.reconciliation.repository import (
    SupplierExecutionReconciliationRepository,
)
from supplier.reconciliation.service import (
    SupplierExecutionReconciliationService,
)


VARIANT_ID = "gid://shopify/ProductVariant/111"
INVENTORY_ITEM_ID = "gid://shopify/InventoryItem/222"
LOCATION_ID = "gid://shopify/Location/333"
OPERATION_ID = "11111111-2222-3333-4444-555555555555"
FINGERPRINT = "a" * 64


def make_factory():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    connection.executescript(
        """
        CREATE TABLE variants (
            shopify_variant_id TEXT PRIMARY KEY,
            sku TEXT,
            inventory_quantity INTEGER,
            synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            status TEXT NOT NULL,
            products_seen INTEGER DEFAULT 0,
            variants_seen INTEGER DEFAULT 0,
            error_message TEXT
        );
        """
    )

    @contextmanager
    def factory():
        try:
            yield connection
        finally:
            connection.commit()

    return connection, factory


def audit_event(
    *,
    event_type,
    baseline=0,
    observed_after=None,
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
        baseline_sync_run_id=baseline,
    )


def seed_verified_execution(
    *,
    factory,
    baseline=0,
):
    repo = SupplierExecutionAuditRepository(
        connection_factory=factory
    )

    repo.append(
        audit_event(
            event_type=(
                SupplierExecutionEventType
                .EXECUTION_STARTED
            ),
            baseline=baseline,
        )
    )

    repo.append(
        audit_event(
            event_type=(
                SupplierExecutionEventType
                .EXECUTION_VERIFIED
            ),
            baseline=baseline,
            observed_after=25,
        )
    )


def insert_success_run(
    connection,
):
    cursor = connection.execute(
        """
        INSERT INTO sync_runs (
            status,
            completed_at,
            products_seen,
            variants_seen
        )
        VALUES (
            'success',
            CURRENT_TIMESTAMP,
            3,
            4
        );
        """
    )
    connection.commit()
    return cursor.lastrowid


def test_execution_schema_has_baseline_column():
    connection, _ = make_factory()

    ensure_supplier_execution_schema(
        connection
    )

    columns = {
        row["name"]
        for row in connection.execute(
            """
            PRAGMA table_info(
                supplier_execution_events
            );
            """
        ).fetchall()
    }

    assert "baseline_sync_run_id" in columns


def test_execution_schema_migrates_e1_table():
    connection, _ = make_factory()

    connection.execute(
        """
        CREATE TABLE supplier_execution_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            supplier_code TEXT NOT NULL,
            supplier_sku TEXT NOT NULL,
            shopify_variant_id TEXT NOT NULL,
            shopify_sku TEXT NOT NULL,
            inventory_item_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            before_quantity INTEGER NOT NULL,
            requested_quantity INTEGER NOT NULL,
            observed_after_quantity INTEGER,
            inventory_delta INTEGER NOT NULL,
            plan_fingerprint TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(operation_id, event_type)
        );
        """
    )

    ensure_supplier_execution_schema(
        connection
    )

    columns = {
        row["name"]
        for row in connection.execute(
            """
            PRAGMA table_info(
                supplier_execution_events
            );
            """
        ).fetchall()
    }

    assert "baseline_sync_run_id" in columns


def test_reconciliation_schema_is_append_only():
    connection, factory = make_factory()

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )
    repo.ensure_schema()

    seed_verified_execution(
        factory=factory
    )
    run_id = insert_success_run(
        connection
    )

    repo.append(
        ReconciliationObservation(
            operation_id=OPERATION_ID,
            verified_event_id=2,
            sync_run_id=run_id,
            shopify_variant_id=VARIANT_ID,
            shopify_sku="AUTO-Cap-001",
            expected_quantity=25,
            observed_sqlite_quantity=25,
            status=ReconciliationStatus.MATCH,
        )
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            UPDATE supplier_execution_reconciliations
            SET status = 'mismatch'
            WHERE reconciliation_id = 1;
            """
        )


def test_reconciliation_delete_is_blocked():
    connection, factory = make_factory()

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )

    seed_verified_execution(
        factory=factory
    )
    run_id = insert_success_run(
        connection
    )

    repo.append(
        ReconciliationObservation(
            operation_id=OPERATION_ID,
            verified_event_id=2,
            sync_run_id=run_id,
            shopify_variant_id=VARIANT_ID,
            shopify_sku="AUTO-Cap-001",
            expected_quantity=25,
            observed_sqlite_quantity=25,
            status=ReconciliationStatus.MATCH,
        )
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            DELETE FROM supplier_execution_reconciliations
            WHERE reconciliation_id = 1;
            """
        )


def test_no_verified_execution_produces_no_reconciliation():
    _, factory = make_factory()

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierExecutionReconciliationService(
            repo
        )
    )

    summary = service.reconcile_all()

    assert summary.verified_operations_seen == 0
    assert summary.reconciliations_written == 0


def test_verified_execution_waits_without_newer_v1_run():
    connection, factory = make_factory()

    baseline = insert_success_run(
        connection
    )

    seed_verified_execution(
        factory=factory,
        baseline=baseline,
    )

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierExecutionReconciliationService(
            repo
        )
    )

    summary = service.reconcile_all()

    assert summary.waiting_for_new_v1_sync == 1
    assert summary.reconciliations_written == 0


def test_success_run_before_baseline_is_not_accepted():
    connection, factory = make_factory()

    old_run = insert_success_run(
        connection
    )

    seed_verified_execution(
        factory=factory,
        baseline=old_run + 5,
    )

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )

    assert (
        repo.latest_successful_sync_after(
            old_run + 5
        )
        is None
    )


def test_newer_success_run_is_selected():
    connection, factory = make_factory()

    baseline = insert_success_run(
        connection
    )
    new_run = insert_success_run(
        connection
    )

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )

    result = (
        repo.latest_successful_sync_after(
            baseline
        )
    )

    assert result["id"] == new_run


def test_match_is_written_when_v1_observes_expected_quantity():
    connection, factory = make_factory()

    baseline = insert_success_run(
        connection
    )
    seed_verified_execution(
        factory=factory,
        baseline=baseline,
    )

    connection.execute(
        """
        INSERT INTO variants (
            shopify_variant_id,
            sku,
            inventory_quantity
        )
        VALUES (?, ?, ?);
        """,
        (
            VARIANT_ID,
            "AUTO-Cap-001",
            25,
        ),
    )
    insert_success_run(
        connection
    )

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierExecutionReconciliationService(
            repo
        )
    )

    summary = service.reconcile_all()

    assert summary.matches_written == 1
    assert summary.mismatches_written == 0
    assert repo.count_events() == 1
    assert repo.get_recent(
        limit=1
    )[0].status == "match"


def test_mismatch_is_written_when_v1_observes_different_quantity():
    connection, factory = make_factory()

    baseline = insert_success_run(
        connection
    )
    seed_verified_execution(
        factory=factory,
        baseline=baseline,
    )

    connection.execute(
        """
        INSERT INTO variants (
            shopify_variant_id,
            sku,
            inventory_quantity
        )
        VALUES (?, ?, ?);
        """,
        (
            VARIANT_ID,
            "AUTO-Cap-001",
            24,
        ),
    )
    insert_success_run(
        connection
    )

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierExecutionReconciliationService(
            repo
        )
    )

    summary = service.reconcile_all()

    assert summary.mismatches_written == 1
    assert (
        repo.get_recent(
            limit=1
        )[0].observed_sqlite_quantity
        == 24
    )


def test_variant_missing_is_written_after_newer_success_run():
    connection, factory = make_factory()

    baseline = insert_success_run(
        connection
    )
    seed_verified_execution(
        factory=factory,
        baseline=baseline,
    )
    insert_success_run(
        connection
    )

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierExecutionReconciliationService(
            repo
        )
    )

    summary = service.reconcile_all()

    assert (
        summary.missing_variants_written
        == 1
    )
    assert (
        repo.get_recent(
            limit=1
        )[0].status
        == "variant_missing"
    )


def test_match_resolves_operation_and_prevents_future_events():
    connection, factory = make_factory()

    baseline = insert_success_run(
        connection
    )
    seed_verified_execution(
        factory=factory,
        baseline=baseline,
    )

    connection.execute(
        """
        INSERT INTO variants (
            shopify_variant_id,
            sku,
            inventory_quantity
        )
        VALUES (?, ?, 25);
        """,
        (
            VARIANT_ID,
            "AUTO-Cap-001",
        ),
    )
    insert_success_run(
        connection
    )

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierExecutionReconciliationService(
            repo
        )
    )

    first = service.reconcile_all()
    insert_success_run(
        connection
    )
    second = service.reconcile_all()

    assert first.matches_written == 1
    assert second.already_matched == 1
    assert repo.count_events() == 1


def test_mismatch_can_be_retried_by_newer_v1_sync():
    connection, factory = make_factory()

    baseline = insert_success_run(
        connection
    )
    seed_verified_execution(
        factory=factory,
        baseline=baseline,
    )

    connection.execute(
        """
        INSERT INTO variants (
            shopify_variant_id,
            sku,
            inventory_quantity
        )
        VALUES (?, ?, 24);
        """,
        (
            VARIANT_ID,
            "AUTO-Cap-001",
        ),
    )
    insert_success_run(
        connection
    )

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )
    service = (
        SupplierExecutionReconciliationService(
            repo
        )
    )

    first = service.reconcile_all()
    assert first.mismatches_written == 1

    connection.execute(
        """
        UPDATE variants
        SET inventory_quantity = 25
        WHERE shopify_variant_id = ?;
        """,
        (
            VARIANT_ID,
        ),
    )
    insert_success_run(
        connection
    )

    second = service.reconcile_all()

    assert second.matches_written == 1
    assert repo.count_events() == 2


def test_same_operation_and_sync_run_is_idempotent():
    connection, factory = make_factory()

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )
    repo.ensure_schema()

    run_id = insert_success_run(
        connection
    )

    observation = ReconciliationObservation(
        operation_id=OPERATION_ID,
        verified_event_id=2,
        sync_run_id=run_id,
        shopify_variant_id=VARIANT_ID,
        shopify_sku="AUTO-Cap-001",
        expected_quantity=25,
        observed_sqlite_quantity=25,
        status=ReconciliationStatus.MATCH,
    )

    first = repo.append(
        observation
    )
    second = repo.append(
        observation
    )

    assert first.reconciliation_id == second.reconciliation_id
    assert second.created_new is False
    assert repo.count_events() == 1


def test_audit_repository_captures_latest_successful_sync_baseline():
    connection, factory = make_factory()

    first_run = insert_success_run(
        connection
    )
    second_run = insert_success_run(
        connection
    )

    repo = SupplierExecutionAuditRepository(
        connection_factory=factory
    )

    assert (
        repo.latest_successful_sync_run_id()
        == second_run
    )
    assert second_run > first_run


def test_started_event_preserves_baseline_value():
    connection, factory = make_factory()

    baseline = insert_success_run(
        connection
    )

    repo = SupplierExecutionAuditRepository(
        connection_factory=factory
    )

    repo.append(
        audit_event(
            event_type=(
                SupplierExecutionEventType
                .EXECUTION_STARTED
            ),
            baseline=baseline,
        )
    )

    stored = repo.get_started_event(
        OPERATION_ID
    )

    assert stored.baseline_sync_run_id == baseline


def test_verified_candidate_exposes_baseline():
    connection, factory = make_factory()

    baseline = insert_success_run(
        connection
    )
    seed_verified_execution(
        factory=factory,
        baseline=baseline,
    )

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )

    candidate = (
        repo.get_verified_execution_candidates()[0]
    )

    assert candidate.baseline_sync_run_id == baseline
    assert candidate.expected_quantity == 25


def test_recent_reconciliation_limit_validation():
    _, factory = make_factory()

    repo = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )

    with pytest.raises(
        ValueError,
        match="positive integer",
    ):
        repo.get_recent(
            limit=0
        )


def test_failed_execution_is_not_reconciliation_candidate():
    _, factory = make_factory()

    repo = SupplierExecutionAuditRepository(
        connection_factory=factory
    )

    repo.append(
        SupplierExecutionAuditEvent(
            operation_id=OPERATION_ID,
            event_type=(
                SupplierExecutionEventType
                .EXECUTION_FAILED
            ),
            supplier_code="demo_supplier",
            supplier_sku="SUP-CAP-001",
            shopify_variant_id=VARIANT_ID,
            shopify_sku="AUTO-Cap-001",
            inventory_item_id=INVENTORY_ITEM_ID,
            location_id=LOCATION_ID,
            before_quantity=1,
            requested_quantity=25,
            observed_after_quantity=None,
            inventory_delta=24,
            plan_fingerprint=FINGERPRINT,
            idempotency_key=OPERATION_ID,
            error_message="rejected",
            baseline_sync_run_id=0,
        )
    )

    recon = (
        SupplierExecutionReconciliationRepository(
            connection_factory=factory
        )
    )

    assert (
        recon.get_verified_execution_candidates()
        == []
    )
