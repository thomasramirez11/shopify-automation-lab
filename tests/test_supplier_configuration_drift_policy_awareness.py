import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from database.supplier_orchestration_schema import ensure_supplier_orchestration_schema
from supplier.orchestration.models import (
    SupplierNextAction,
    SupplierOperationsBacklog,
    SupplierSystemPosture,
)
from supplier.orchestration.run_models import (
    ConfigurationTransitionType,
    OrchestrationTransitionType,
    policy_version_label,
)
from supplier.orchestration.run_repository import SupplierOrchestrationRunRepository
from supplier.orchestration.run_service import SupplierOrchestrationRunService


def factory():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    @contextmanager
    def connection_factory():
        try:
            yield connection
        finally:
            connection.commit()

    return connection, connection_factory


def snapshot(
    *,
    fingerprint="a" * 64,
    manifest_fingerprint="b" * 64,
    policy_fingerprint="c" * 64,
    posture=SupplierSystemPosture.IDLE,
    next_action=SupplierNextAction.NONE,
):
    return SimpleNamespace(
        supplier_code="demo_supplier",
        orchestration_fingerprint=fingerprint,
        manifest=SimpleNamespace(manifest_fingerprint=manifest_fingerprint),
        policy_fingerprint=policy_fingerprint,
        posture=posture,
        next_action=next_action,
        plan=SimpleNamespace(
            planned_mutations=0,
            review_items=0,
            blocked_items=0,
            no_action_items=2,
        ),
        backlog=SupplierOperationsBacklog(resolution_closed=3),
    )


def service(connection_factory):
    repo = SupplierOrchestrationRunRepository(connection_factory=connection_factory)
    return repo, SupplierOrchestrationRunService(repo)


def test_fresh_schema_contains_drift_columns():
    connection, _ = factory()
    ensure_supplier_orchestration_schema(connection)
    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(supplier_orchestration_runs);"
        ).fetchall()
    }
    assert {
        "policy_fingerprint",
        "previous_policy_fingerprint",
        "policy_changed",
        "manifest_changed",
        "snapshot_changed",
    }.issubset(columns)


def test_old_schema_migrates_without_losing_row():
    connection, _ = factory()
    connection.executescript(
        """
        CREATE TABLE supplier_orchestration_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_code TEXT NOT NULL,
            orchestration_fingerprint TEXT NOT NULL,
            manifest_fingerprint TEXT NOT NULL,
            posture TEXT NOT NULL,
            next_action TEXT NOT NULL,
            planned_mutations INTEGER NOT NULL,
            review_items INTEGER NOT NULL,
            blocked_items INTEGER NOT NULL,
            no_action_items INTEGER NOT NULL,
            queued_retry_attempts INTEGER NOT NULL,
            dead_letter_awaiting_human INTEGER NOT NULL,
            dead_letter_acknowledged INTEGER NOT NULL,
            resolution_recorded INTEGER NOT NULL,
            reentry_authorized INTEGER NOT NULL,
            reentry_started INTEGER NOT NULL,
            reentry_failed INTEGER NOT NULL,
            resolution_closed INTEGER NOT NULL,
            previous_run_id INTEGER,
            previous_posture TEXT,
            posture_changed INTEGER NOT NULL,
            next_action_changed INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO supplier_orchestration_runs (
            supplier_code, orchestration_fingerprint, manifest_fingerprint,
            posture, next_action,
            planned_mutations, review_items, blocked_items, no_action_items,
            queued_retry_attempts, dead_letter_awaiting_human,
            dead_letter_acknowledged, resolution_recorded, reentry_authorized,
            reentry_started, reentry_failed, resolution_closed,
            previous_run_id, previous_posture, posture_changed,
            next_action_changed
        ) VALUES (
            'demo_supplier',
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
            'idle', 'none',
            0,0,0,2, 0,0,0,0,0,0,0,3,
            NULL,NULL,0,0
        );
        """
    )
    ensure_supplier_orchestration_schema(connection)
    row = connection.execute(
        "SELECT * FROM supplier_orchestration_runs WHERE run_id=1;"
    ).fetchone()
    assert row is not None
    assert row["policy_fingerprint"] == ""
    assert row["policy_changed"] == 0


def test_migration_is_idempotent():
    connection, _ = factory()
    ensure_supplier_orchestration_schema(connection)
    ensure_supplier_orchestration_schema(connection)


def test_first_run_is_initial_for_both_dimensions():
    _, cf = factory()
    _, svc = service(cf)
    result = svc.record_snapshot(snapshot())
    assert result.transition_type == OrchestrationTransitionType.INITIAL
    assert result.configuration_transition_type == ConfigurationTransitionType.INITIAL


def test_identical_second_run_is_fully_unchanged():
    _, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    result = svc.record_snapshot(snapshot())
    assert result.transition_type == OrchestrationTransitionType.UNCHANGED
    assert result.configuration_transition_type == ConfigurationTransitionType.UNCHANGED
    assert result.run.snapshot_changed == 0


def test_policy_change_is_detected_while_operational_state_unchanged():
    _, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    result = svc.record_snapshot(
        snapshot(policy_fingerprint="d" * 64, fingerprint="e" * 64)
    )
    assert result.transition_type == OrchestrationTransitionType.UNCHANGED
    assert result.configuration_transition_type == ConfigurationTransitionType.POLICY_CHANGED
    assert result.run.policy_changed == 1
    assert result.run.snapshot_changed == 1


def test_manifest_change_is_detected():
    _, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    result = svc.record_snapshot(
        snapshot(manifest_fingerprint="d" * 64, fingerprint="e" * 64)
    )
    assert result.configuration_transition_type == ConfigurationTransitionType.MANIFEST_CHANGED
    assert result.run.manifest_changed == 1


def test_policy_and_manifest_change_is_detected():
    _, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    result = svc.record_snapshot(
        snapshot(
            policy_fingerprint="d" * 64,
            manifest_fingerprint="e" * 64,
            fingerprint="f" * 64,
        )
    )
    assert result.configuration_transition_type == ConfigurationTransitionType.POLICY_AND_MANIFEST_CHANGED


def test_snapshot_only_change_is_not_configuration_change():
    _, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    result = svc.record_snapshot(snapshot(fingerprint="d" * 64))
    assert result.run.snapshot_changed == 1
    assert result.run.policy_changed == 0
    assert result.run.manifest_changed == 0
    assert result.configuration_transition_type == ConfigurationTransitionType.UNCHANGED


def test_previous_policy_fingerprint_is_preserved():
    _, cf = factory()
    _, svc = service(cf)
    first = svc.record_snapshot(snapshot(policy_fingerprint="c" * 64))
    second = svc.record_snapshot(
        snapshot(policy_fingerprint="d" * 64, fingerprint="e" * 64)
    )
    assert second.run.previous_policy_fingerprint == first.run.policy_fingerprint


def test_current_policy_fingerprint_is_preserved():
    _, cf = factory()
    _, svc = service(cf)
    result = svc.record_snapshot(snapshot(policy_fingerprint="d" * 64))
    assert result.run.policy_fingerprint == "d" * 64


def test_legacy_previous_policy_becomes_detectable_change():
    connection, cf = factory()
    ensure_supplier_orchestration_schema(connection)
    connection.execute(
        """
        INSERT INTO supplier_orchestration_runs (
            supplier_code, orchestration_fingerprint, manifest_fingerprint,
            policy_fingerprint, posture, next_action,
            planned_mutations, review_items, blocked_items, no_action_items,
            queued_retry_attempts, dead_letter_awaiting_human,
            dead_letter_acknowledged, resolution_recorded, reentry_authorized,
            reentry_started, reentry_failed, resolution_closed,
            previous_run_id, previous_posture, previous_policy_fingerprint,
            posture_changed, next_action_changed, policy_changed,
            manifest_changed, snapshot_changed
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
        """,
        (
            "demo_supplier", "a" * 64, "b" * 64, "", "idle", "none",
            0,0,0,2, 0,0,0,0,0,0,0,3,
            None,None,None, 0,0,0,0,0,
        ),
    )
    connection.commit()
    _, svc = service(cf)
    result = svc.record_snapshot(
        snapshot(policy_fingerprint="c" * 64, fingerprint="d" * 64)
    )
    assert result.run.policy_changed == 1
    assert result.run.previous_policy_fingerprint == ""
    assert (
        result.configuration_transition_type
        == ConfigurationTransitionType.POLICY_PROVENANCE_ESTABLISHED
    )


def test_policy_version_label_is_human_friendly():
    assert policy_version_label("c44718747ae7" + "0" * 52) == "POLICY-C44718747AE7"


def test_legacy_policy_label_does_not_invent_version():
    assert policy_version_label("") == "LEGACY-UNRECORDED"


def test_configuration_changed_property_true():
    _, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    result = svc.record_snapshot(
        snapshot(policy_fingerprint="d" * 64, fingerprint="e" * 64)
    )
    assert result.configuration_changed is True


def test_configuration_changed_property_false_when_same():
    _, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    result = svc.record_snapshot(snapshot())
    assert result.configuration_changed is False


def test_any_snapshot_change_property_true():
    _, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    result = svc.record_snapshot(snapshot(fingerprint="d" * 64))
    assert result.any_snapshot_change is True


def test_operational_change_can_happen_without_policy_change():
    _, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    result = svc.record_snapshot(
        snapshot(
            posture=SupplierSystemPosture.READY_FOR_APPROVAL,
            next_action=SupplierNextAction.APPROVE_BATCH,
            fingerprint="d" * 64,
        )
    )
    assert result.transition_type == OrchestrationTransitionType.POSTURE_AND_ACTION_CHANGED
    assert result.run.policy_changed == 0


def test_recent_runs_expose_new_fields():
    _, cf = factory()
    repo, svc = service(cf)
    svc.record_snapshot(snapshot())
    run = repo.get_recent(supplier_code="demo_supplier", limit=1)[0]
    assert hasattr(run, "policy_fingerprint")
    assert hasattr(run, "snapshot_changed")


def test_append_only_update_is_still_blocked():
    connection, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "UPDATE supplier_orchestration_runs SET policy_changed=1;"
        )


def test_append_only_delete_is_still_blocked():
    connection, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM supplier_orchestration_runs;")


def test_same_policy_different_manifest_is_not_policy_drift():
    _, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    result = svc.record_snapshot(
        snapshot(manifest_fingerprint="d" * 64, fingerprint="e" * 64)
    )
    assert result.run.policy_changed == 0
    assert result.run.manifest_changed == 1


def test_same_manifest_different_policy_is_not_manifest_drift():
    _, cf = factory()
    _, svc = service(cf)
    svc.record_snapshot(snapshot())
    result = svc.record_snapshot(
        snapshot(policy_fingerprint="d" * 64, fingerprint="e" * 64)
    )
    assert result.run.policy_changed == 1
    assert result.run.manifest_changed == 0


def test_first_run_change_flags_are_false():
    _, cf = factory()
    _, svc = service(cf)
    result = svc.record_snapshot(snapshot())
    assert result.run.policy_changed == 0
    assert result.run.manifest_changed == 0
    assert result.run.snapshot_changed == 0


def test_policy_change_keeps_previous_run_link():
    _, cf = factory()
    _, svc = service(cf)
    first = svc.record_snapshot(snapshot())
    second = svc.record_snapshot(
        snapshot(policy_fingerprint="d" * 64, fingerprint="e" * 64)
    )
    assert second.run.previous_run_id == first.run.run_id
