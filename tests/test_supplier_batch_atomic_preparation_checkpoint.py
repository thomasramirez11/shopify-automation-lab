"""V2.8B/4 atomic intent/snapshot durability, replay and safety checks.

Only synthetic preflight and temporary SQLite databases are involved.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

import pytest

from scripts.supplier_batch_recovery_synthetic_demo import build_prepared
from supplier.batch.live_atomic_preparation import SupplierLiveBatchAtomicPreparationRepository
from supplier.batch.live_intent_repository import IntentConflict, SupplierLiveBatchIntentRepository
from supplier.batch.live_recovery_models import RecoveryConflict, RecoveryState
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService


@pytest.fixture
def db_rig(tmp_path):
    path = tmp_path / "atomic.sqlite3"

    @contextmanager
    def connection():
        db = sqlite3.connect(path)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def make_service():
        return SupplierLiveBatchRecoveryService(
            intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connection),
            recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connection),
        )

    return connection, make_service, SupplierLiveBatchAtomicPreparationRepository(connection_factory=connection)


def counts(connection):
    with connection() as db:
        return tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in (
                         "supplier_live_batch_intents",
                         "supplier_live_batch_request_snapshots",
                         "supplier_live_batch_dispatch_events",
                     ))


def prepare_once(db_rig):
    connect, make_service, _ = db_rig
    prepared = build_prepared()
    snapshot = make_service().prepare(prepared)
    return prepared, snapshot, connect, make_service


def test_first_atomic_prepare_inserts_both_rows(db_rig):
    prepared, snapshot, connect, make_service = prepare_once(db_rig)
    assert counts(connect) == (1, 1, 0)
    assert snapshot.operation_id == prepared.preview.operation_id
    assert snapshot.request_digest == prepared.request_digest
    assert make_service().decision(operation_id=prepared.preview.operation_id).state is RecoveryState.PREPARED_NOT_SENT


def test_valid_snapshot_has_cas_exact_targets(db_rig):
    prepared, snapshot, _, _ = prepare_once(db_rig)
    assert snapshot.payload["variables"] == prepared.preview.variables
    assert [q["changeFromQuantity"] for q in snapshot.payload["variables"]["input"]["quantities"]] == [25, 40]
    assert [q["quantity"] for q in snapshot.payload["variables"]["input"]["quantities"]] == [26, 42]
    assert snapshot.payload["variables"]["idempotencyKey"] == prepared.preview.operation_id


def test_same_operation_replay_idempotent(db_rig):
    prepared, snapshot, connect, make_service = prepare_once(db_rig)
    assert make_service().prepare(prepared) == snapshot
    assert counts(connect) == (1, 1, 0)


def test_same_manifest_different_operation_blocked(db_rig):
    prepared, _, connect, make_service = prepare_once(db_rig)
    with pytest.raises(IntentConflict, match="already reserved"):
        make_service().prepare(build_prepared())
    assert counts(connect) == (1, 1, 0)


def test_different_operation_id_same_request_digest_rejected(db_rig):
    prepared, _, connect, make_service = prepare_once(db_rig)
    with pytest.raises(IntentConflict):
        make_service().prepare(replace(prepared, preview=replace(prepared.preview, operation_id=str(uuid4()))))
    assert counts(connect) == (1, 1, 0)


@pytest.mark.parametrize("alteration", [
    lambda p: replace(p, request_digest="a" * 64),
    lambda p: replace(p, location_id="gid://shopify/Location/999002"),
    lambda p: replace(p, mode="EXECUTE"),
    lambda p: replace(p, preview=replace(p.preview, mode="EXECUTE")),
    lambda p: replace(p, preflight=replace(p.preflight, approved_manifest_fingerprint="f" * 64)),
    lambda p: replace(p, preflight=replace(p.preflight, location_id="gid://shopify/Location/999002")),
])
def test_invalid_preparation_rejected_without_any_rows(db_rig, alteration):
    connect, make_service, _ = db_rig
    with pytest.raises((IntentConflict, RecoveryConflict)):
        make_service().prepare(alteration(build_prepared()))
    # Invalid preflight is rejected before schema initialization in this path.
    with connect() as db:
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        assert not tables


@pytest.mark.parametrize("part,update", [
    (0, {"quantity": 999}),
    (1, {"changeFromQuantity": 17}),
    (0, {"inventoryItemId": "gid://shopify/InventoryItem/777"}),
    (1, {"locationId": "gid://shopify/Location/999002"}),
])
def test_tampered_nested_request_denied(db_rig, part, update):
    connect, make_service, _ = db_rig
    prepared = build_prepared()
    prepared.preview.variables["input"]["quantities"][part].update(update)
    with pytest.raises(IntentConflict):
        make_service().prepare(prepared)
    with connect() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='supplier_live_batch_intents'").fetchone()


def test_bad_uuid_denied(db_rig):
    _, make_service, _ = db_rig
    prepared = build_prepared()
    with pytest.raises(IntentConflict, match="invalid operation id|UUIDv4"):
        make_service().prepare(replace(prepared, preview=replace(prepared.preview, operation_id="wrong")))


def test_failed_snapshot_insert_rolls_back_new_intent(db_rig):
    connect, make_service, atomic = db_rig
    with connect() as db:
        atomic._initialize(db)
        db.executescript("""CREATE TRIGGER artificial_disk_failure
            BEFORE INSERT ON supplier_live_batch_request_snapshots
            BEGIN SELECT RAISE(ABORT, 'simulated snapshot disk failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        make_service().prepare(build_prepared())
    assert counts(connect) == (0, 0, 0)


def test_injected_snapshot_abort_leaves_reusable_manifest(db_rig):
    connect, make_service, atomic = db_rig
    with connect() as db:
        atomic._initialize(db)
        db.executescript("""CREATE TRIGGER inject_failure
            AFTER INSERT ON supplier_live_batch_request_snapshots
            BEGIN SELECT RAISE(ABORT, 'simulated crash before commit'); END;""")
    prepared = build_prepared()
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        make_service().prepare(prepared)
    assert counts(connect) == (0, 0, 0)
    with connect() as db:
        db.execute("DROP TRIGGER inject_failure")
    make_service().prepare(prepared)
    assert counts(connect) == (1, 1, 0)


def test_partial_legacy_intent_not_auto_repaired(db_rig):
    connect, make_service, _ = db_rig
    prepared = build_prepared()
    SupplierLiveBatchIntentRepository(connection_factory=connect).reserve(prepared)
    with pytest.raises(RecoveryConflict, match="partial pre-existing"):
        make_service().prepare(prepared)
    assert counts(connect) == (1, 0, 0)


def test_partial_legacy_intent_different_uuid_stays_blocked(db_rig):
    connect, make_service, _ = db_rig
    SupplierLiveBatchIntentRepository(connection_factory=connect).reserve(build_prepared())
    with pytest.raises(IntentConflict):
        make_service().prepare(build_prepared())
    assert counts(connect) == (1, 0, 0)


def test_replay_after_arm_blocked(db_rig):
    prepared, _, connect, make_service = prepare_once(db_rig)
    service = make_service()
    service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    with pytest.raises(RecoveryConflict, match="history"):
        make_service().prepare(prepared)
    assert counts(connect) == (1, 1, 1)


def test_replay_after_readback_blocked(db_rig):
    prepared, _, connect, make_service = prepare_once(db_rig)
    service = make_service()
    service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    service.note_outcome_unknown(operation_id=prepared.preview.operation_id)
    with pytest.raises(RecoveryConflict, match="history"):
        make_service().prepare(prepared)
    assert counts(connect) == (1, 1, 2)


def test_prepared_restart_same_snapshot(db_rig):
    prepared, snapshot, connect, make_service = prepare_once(db_rig)
    restarted = make_service()
    assert restarted._recovery.load_snapshot(prepared.preview.operation_id) == snapshot
    assert restarted.decision(operation_id=prepared.preview.operation_id).state is RecoveryState.PREPARED_NOT_SENT
    assert counts(connect) == (1, 1, 0)


def test_forged_existing_snapshot_denied(db_rig):
    prepared, _, connect, make_service = prepare_once(db_rig)
    with connect() as db:
        db.execute("DROP TRIGGER trg_supplier_live_batch_snapshots_no_update")
        db.execute("UPDATE supplier_live_batch_request_snapshots SET payload_json='{}'")
    with pytest.raises(RecoveryConflict, match="immutable snapshot"):
        make_service().prepare(prepared)
    assert counts(connect) == (1, 1, 0)


def test_mutated_in_memory_after_commit_denied(db_rig):
    prepared, snapshot, connect, make_service = prepare_once(db_rig)
    prepared.preview.variables["input"]["quantities"][0]["quantity"] = 123
    with pytest.raises(IntentConflict):
        make_service().prepare(prepared)
    assert make_service()._recovery.load_snapshot(prepared.preview.operation_id) == snapshot
    assert counts(connect) == (1, 1, 0)


def test_no_shopify_dependency_used_during_prepare(monkeypatch, db_rig):
    connect, make_service, _ = db_rig
    from shopify import client
    def forbidden(*args, **kwargs):
        raise AssertionError("Shopify must not be used")
    monkeypatch.setattr(client.ShopifyClient, "__init__", forbidden)
    prepared = build_prepared()
    make_service().prepare(prepared)
    assert counts(connect) == (1, 1, 0)


def test_different_connection_factories_fail_closed(db_rig):
    connect, _, _ = db_rig
    @contextmanager
    def different():
        with connect() as db:
            yield db
    service = SupplierLiveBatchRecoveryService(
        intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connect),
        recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=different),
    )
    with pytest.raises(RecoveryConflict, match="shared SQLite"):
        service.prepare(build_prepared())
    with connect() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='supplier_live_batch_intents'").fetchone()


def test_schema_enforces_foreign_keys(db_rig):
    connect, make_service, _ = db_rig
    prepare_once(db_rig)
    with connect() as db:
        db.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("""INSERT INTO supplier_live_batch_request_snapshots
                (operation_id, request_digest, payload_json, payload_sha256)
                VALUES ('none', 'x', '{}', 'x')""")


def test_atomic_repo_direct_access_requires_valid_preflight(db_rig):
    connect, _, atomic = db_rig
    with pytest.raises(IntentConflict):
        atomic.prepare(replace(build_prepared(), preflight_fingerprint="bad"))
    with connect() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='supplier_live_batch_intents'").fetchone()


def test_atomic_preparation_demo_prints_expected(capsys):
    from scripts.supplier_batch_atomic_preparation_demo import main
    assert main() == 0
    output = capsys.readouterr().out
    assert "INTENTS: 1" in output
    assert "SNAPSHOTS: 1" in output
    assert "DISPATCH EVENTS: 0" in output
    assert "EXECUTION DISABLED" in output
