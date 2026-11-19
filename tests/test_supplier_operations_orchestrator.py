import sqlite3
from contextlib import contextmanager
from decimal import Decimal

import pytest

from supplier.batch.models import BatchSafetyPolicy
from supplier.comparison.models import ShopifyVariantState
from supplier.comparison.snapshot import ShopifyComparisonSnapshot
from supplier.decision.models import InventorySyncPolicy
from supplier.mapping.models import SupplierVariantMapping
from supplier.models import SupplierProduct
from supplier.orchestration.backlog import (
    SQLiteSupplierOperationsBacklogReader,
)
from supplier.orchestration.models import (
    SupplierNextAction,
    SupplierOperationsBacklog,
    SupplierSystemPosture,
)
from supplier.orchestration.orchestrator import (
    SupplierOperationsOrchestrator,
)


class FakeSupplierAdapter:
    def __init__(self, products):
        self._products = tuple(products)

    def list_products(self):
        return self._products


class FakeRegistry:
    def __init__(self, mappings):
        self._mappings = tuple(mappings)

    def list_mappings(
        self,
        *,
        active_only=True,
    ):
        if not active_only:
            return self._mappings

        return tuple(
            mapping
            for mapping in self._mappings
            if mapping.active
        )


class FakeMappingLoader:
    def __init__(self, mappings):
        self._mappings = mappings

    def load_registry(self):
        return FakeRegistry(
            self._mappings
        )


class FakeSnapshotAdapter:
    def __init__(self, snapshots):
        self._snapshots = dict(
            snapshots
        )

    def get_snapshot(
        self,
        shopify_variant_id,
    ):
        return self._snapshots.get(
            shopify_variant_id
        )


class FakeBacklogReader:
    def __init__(self, backlog):
        self._backlog = backlog

    def read(self):
        return self._backlog


def build_orchestrator(
    *,
    supplier_inventory=25,
    shopify_inventory=25,
    backlog=None,
    supplier_code="demo_supplier",
    mapping_supplier_code="demo_supplier",
    max_item_delta=50,
):
    variant_id = (
        "gid://shopify/ProductVariant/100"
    )

    product = SupplierProduct(
        supplier_sku="SUP-100",
        title="Demo",
        stock_quantity=(
            supplier_inventory
        ),
        unit_cost=Decimal("10.00"),
        currency="USD",
    )

    mapping = SupplierVariantMapping(
        supplier_code=(
            mapping_supplier_code
        ),
        supplier_sku="SUP-100",
        shopify_variant_id=(
            variant_id
        ),
        shopify_sku="SHOP-100",
        active=True,
    )

    snapshot = ShopifyComparisonSnapshot(
        shopify_variant=(
            ShopifyVariantState(
                shopify_variant_id=(
                    variant_id
                ),
                shopify_sku="SHOP-100",
                inventory_quantity=(
                    shopify_inventory
                ),
            )
        ),
        stored_cost=(
            Decimal("10.00")
        ),
        cost_currency="USD",
        cost_source="test",
    )

    return SupplierOperationsOrchestrator(
        supplier_code=supplier_code,
        supplier_adapter=(
            FakeSupplierAdapter(
                [
                    product
                ]
            )
        ),
        mapping_loader=(
            FakeMappingLoader(
                [
                    mapping
                ]
            )
        ),
        snapshot_adapter=(
            FakeSnapshotAdapter(
                {
                    variant_id:
                        snapshot
                }
            )
        ),
        item_policy=(
            InventorySyncPolicy(
                max_inventory_delta=(
                    max_item_delta
                )
            )
        ),
        batch_policy=(
            BatchSafetyPolicy(
                max_mutations_per_batch=5,
                max_total_absolute_inventory_delta=100,
                max_single_item_absolute_delta=50,
            )
        ),
        backlog_reader=(
            FakeBacklogReader(
                backlog
                or SupplierOperationsBacklog()
            )
        ),
    )


def test_idle_when_supplier_matches_shopify():
    snapshot = (
        build_orchestrator()
        .build_snapshot()
    )

    assert snapshot.posture == SupplierSystemPosture.IDLE
    assert snapshot.next_action == SupplierNextAction.NONE
    assert snapshot.plan.planned_mutations == 0


def test_ready_for_approval_when_safe_mutation_exists():
    snapshot = (
        build_orchestrator(
            supplier_inventory=30,
            shopify_inventory=25,
        )
        .build_snapshot()
    )

    assert (
        snapshot.posture
        == SupplierSystemPosture.READY_FOR_APPROVAL
    )
    assert (
        snapshot.next_action
        == SupplierNextAction.APPROVE_BATCH
    )
    assert snapshot.plan.planned_mutations == 1


def test_large_item_delta_requires_review():
    snapshot = (
        build_orchestrator(
            supplier_inventory=90,
            shopify_inventory=25,
            max_item_delta=50,
        )
        .build_snapshot()
    )

    assert (
        snapshot.posture
        == SupplierSystemPosture.REVIEW_REQUIRED
    )
    assert (
        snapshot.next_action
        == SupplierNextAction.REVIEW_BATCH
    )


def test_human_attention_overrides_idle_pipeline():
    snapshot = (
        build_orchestrator(
            backlog=(
                SupplierOperationsBacklog(
                    dead_letter_awaiting_human=1
                )
            )
        )
        .build_snapshot()
    )

    assert (
        snapshot.posture
        == SupplierSystemPosture.HUMAN_ATTENTION
    )


def test_human_attention_overrides_new_mutation():
    snapshot = (
        build_orchestrator(
            supplier_inventory=30,
            shopify_inventory=25,
            backlog=(
                SupplierOperationsBacklog(
                    dead_letter_acknowledged=1
                )
            ),
        )
        .build_snapshot()
    )

    assert (
        snapshot.posture
        == SupplierSystemPosture.HUMAN_ATTENTION
    )


def test_retry_queue_overrides_ready_batch():
    snapshot = (
        build_orchestrator(
            supplier_inventory=30,
            shopify_inventory=25,
            backlog=(
                SupplierOperationsBacklog(
                    queued_retry_attempts=1
                )
            ),
        )
        .build_snapshot()
    )

    assert (
        snapshot.posture
        == SupplierSystemPosture.RECOVERY_PENDING
    )
    assert (
        snapshot.next_action
        == SupplierNextAction.PROCESS_RETRY_QUEUE
    )


def test_human_attention_overrides_retry_queue():
    snapshot = (
        build_orchestrator(
            backlog=(
                SupplierOperationsBacklog(
                    queued_retry_attempts=2,
                    dead_letter_awaiting_human=1,
                )
            )
        )
        .build_snapshot()
    )

    assert (
        snapshot.posture
        == SupplierSystemPosture.HUMAN_ATTENTION
    )


def test_closed_resolution_does_not_create_attention():
    snapshot = (
        build_orchestrator(
            backlog=(
                SupplierOperationsBacklog(
                    resolution_closed=5
                )
            )
        )
        .build_snapshot()
    )

    assert snapshot.posture == SupplierSystemPosture.IDLE


def test_reentry_failed_requires_human_attention():
    snapshot = (
        build_orchestrator(
            backlog=(
                SupplierOperationsBacklog(
                    reentry_failed=1
                )
            )
        )
        .build_snapshot()
    )

    assert (
        snapshot.posture
        == SupplierSystemPosture.HUMAN_ATTENTION
    )


def test_in_progress_resolution_requires_human_attention():
    snapshot = (
        build_orchestrator(
            backlog=(
                SupplierOperationsBacklog(
                    resolution_recorded=1
                )
            )
        )
        .build_snapshot()
    )

    assert (
        snapshot.posture
        == SupplierSystemPosture.HUMAN_ATTENTION
    )


def test_supplier_code_filters_other_mappings():
    snapshot = (
        build_orchestrator(
            mapping_supplier_code=(
                "other_supplier"
            )
        )
        .build_snapshot()
    )

    assert snapshot.active_mapping_count == 0
    assert snapshot.decision_count == 0


def test_supplier_product_count_is_preserved():
    snapshot = (
        build_orchestrator()
        .build_snapshot()
    )

    assert snapshot.supplier_product_count == 1


def test_active_mapping_count_is_preserved():
    snapshot = (
        build_orchestrator()
        .build_snapshot()
    )

    assert snapshot.active_mapping_count == 1


def test_orchestration_fingerprint_is_deterministic():
    first = (
        build_orchestrator()
        .build_snapshot()
    )

    second = (
        build_orchestrator()
        .build_snapshot()
    )

    assert (
        first.orchestration_fingerprint
        == second.orchestration_fingerprint
    )


def test_orchestration_fingerprint_changes_with_pipeline_state():
    idle = (
        build_orchestrator()
        .build_snapshot()
    )

    ready = (
        build_orchestrator(
            supplier_inventory=30,
            shopify_inventory=25,
        )
        .build_snapshot()
    )

    assert (
        idle.orchestration_fingerprint
        != ready.orchestration_fingerprint
    )


def test_orchestration_fingerprint_changes_with_backlog():
    idle = (
        build_orchestrator()
        .build_snapshot()
    )

    attention = (
        build_orchestrator(
            backlog=(
                SupplierOperationsBacklog(
                    dead_letter_awaiting_human=1
                )
            )
        )
        .build_snapshot()
    )

    assert (
        idle.orchestration_fingerprint
        != attention.orchestration_fingerprint
    )


def test_invalid_supplier_code_is_rejected():
    with pytest.raises(
        ValueError,
        match="supplier_code",
    ):
        build_orchestrator(
            supplier_code=""
        )


def test_backlog_rejects_negative_counts():
    with pytest.raises(
        ValueError,
        match="non-negative integer",
    ):
        SupplierOperationsBacklog(
            queued_retry_attempts=-1
        )


def sqlite_factory(connection):
    @contextmanager
    def factory():
        yield connection

    return factory


def test_sqlite_backlog_reader_handles_missing_tables():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    backlog = (
        SQLiteSupplierOperationsBacklogReader(
            connection_factory=(
                sqlite_factory(
                    connection
                )
            )
        )
        .read()
    )

    assert backlog == SupplierOperationsBacklog()


def test_sqlite_backlog_reader_counts_queued_retry():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    connection.executescript(
        """
        CREATE TABLE supplier_batch_retry_events (
            retry_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            retry_id TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            event_type TEXT NOT NULL
        );

        INSERT INTO supplier_batch_retry_events (
            retry_id,
            attempt_number,
            event_type
        )
        VALUES (
            'r1',
            1,
            'retry_queued'
        );
        """
    )

    backlog = (
        SQLiteSupplierOperationsBacklogReader(
            connection_factory=(
                sqlite_factory(
                    connection
                )
            )
        )
        .read()
    )

    assert backlog.queued_retry_attempts == 1


def test_sqlite_backlog_reader_excludes_started_retry():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    connection.executescript(
        """
        CREATE TABLE supplier_batch_retry_events (
            retry_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            retry_id TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            event_type TEXT NOT NULL
        );

        INSERT INTO supplier_batch_retry_events (
            retry_id,
            attempt_number,
            event_type
        )
        VALUES
            ('r1', 1, 'retry_queued'),
            ('r1', 1, 'retry_started');
        """
    )

    backlog = (
        SQLiteSupplierOperationsBacklogReader(
            connection_factory=(
                sqlite_factory(
                    connection
                )
            )
        )
        .read()
    )

    assert backlog.queued_retry_attempts == 0


def test_sqlite_backlog_reader_counts_open_dlq_without_resolution_table():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    connection.executescript(
        """
        CREATE TABLE supplier_dead_letter_events (
            dead_letter_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            event_type TEXT NOT NULL
        );

        INSERT INTO supplier_dead_letter_events (
            case_id,
            event_type
        )
        VALUES (
            'case-1',
            'case_opened'
        );
        """
    )

    backlog = (
        SQLiteSupplierOperationsBacklogReader(
            connection_factory=(
                sqlite_factory(
                    connection
                )
            )
        )
        .read()
    )

    assert backlog.dead_letter_awaiting_human == 1


def test_sqlite_backlog_reader_counts_acknowledged_dlq_without_resolution_table():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    connection.executescript(
        """
        CREATE TABLE supplier_dead_letter_events (
            dead_letter_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            event_type TEXT NOT NULL
        );

        INSERT INTO supplier_dead_letter_events (
            case_id,
            event_type
        )
        VALUES
            ('case-1', 'case_opened'),
            ('case-1', 'case_acknowledged');
        """
    )

    backlog = (
        SQLiteSupplierOperationsBacklogReader(
            connection_factory=(
                sqlite_factory(
                    connection
                )
            )
        )
        .read()
    )

    assert backlog.dead_letter_acknowledged == 1


def test_sqlite_backlog_reader_excludes_closed_dlq():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    connection.executescript(
        """
        CREATE TABLE supplier_dead_letter_events (
            dead_letter_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            event_type TEXT NOT NULL
        );

        CREATE TABLE supplier_case_resolution_events (
            resolution_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            event_type TEXT NOT NULL
        );

        INSERT INTO supplier_dead_letter_events (
            case_id,
            event_type
        )
        VALUES
            ('case-1', 'case_opened'),
            ('case-1', 'case_acknowledged');

        INSERT INTO supplier_case_resolution_events (
            case_id,
            event_type
        )
        VALUES
            ('case-1', 'resolution_recorded'),
            ('case-1', 'case_closed');
        """
    )

    backlog = (
        SQLiteSupplierOperationsBacklogReader(
            connection_factory=(
                sqlite_factory(
                    connection
                )
            )
        )
        .read()
    )

    assert backlog.dead_letter_awaiting_human == 0
    assert backlog.dead_letter_acknowledged == 0
    assert backlog.resolution_closed == 1


def test_unresolved_human_cases_excludes_closed():
    backlog = SupplierOperationsBacklog(
        dead_letter_awaiting_human=1,
        dead_letter_acknowledged=2,
        resolution_closed=9,
    )

    assert backlog.unresolved_human_cases == 3
