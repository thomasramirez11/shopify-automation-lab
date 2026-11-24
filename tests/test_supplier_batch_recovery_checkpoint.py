"""V2.8B/3: crash safety / integrity tests; no real Shopify I/O."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import replace

import pytest

from scripts.supplier_batch_recovery_synthetic_demo import FakeReadback, build_prepared
from supplier.batch.live_intent_repository import IntentConflict, SupplierLiveBatchIntentRepository
from supplier.batch.live_recovery_models import RecoveryConflict, RecoveryEventKind, RecoveryState
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService


@pytest.fixture
def rig(tmp_path):
    db_path = tmp_path / "isolated-recovery.sqlite3"

    @contextmanager
    def connect():
        db = sqlite3.connect(db_path)
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
            intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connect),
            recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connect),
        )

    return make_service, connect


@pytest.fixture
def staged(rig):
    make_service, connect = rig
    prepared = build_prepared()
    service = make_service()
    service.prepare(prepared)
    return prepared, service, make_service, connect


def test_initial_is_prepared_and_not_sent(staged):
    prepared, service, _, _ = staged
    decision = service.decision(operation_id=prepared.preview.operation_id)
    assert decision.state is RecoveryState.PREPARED_NOT_SENT
    assert not decision.dispatch_allowed and not decision.automatic_retry_allowed
    assert decision.human_review_required is False
    assert decision.event_count == 0


def test_prepared_snapshot_has_exact_query_and_variables(staged):
    prepared, service, _, _ = staged
    loaded = service._recovery.load_snapshot(prepared.preview.operation_id)
    assert loaded.payload["query"] == prepared.preview.query
    assert loaded.payload["variables"] == prepared.preview.variables
    assert loaded.request_digest == prepared.request_digest
    assert loaded.payload["skus"] == list(prepared.preview.skus)


def test_prepare_repeated_same_payload_is_idempotent(staged):
    prepared, service, _, connect = staged
    first = service._recovery.load_snapshot(prepared.preview.operation_id)
    second = service.prepare(prepared)
    assert first == second
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM supplier_live_batch_request_snapshots").fetchone()[0] == 1


def test_prepared_request_is_bound_to_preexisting_intent(rig):
    make_service, _ = rig
    prepared = build_prepared()
    repo = SupplierLiveBatchRecoveryRepository(connection_factory=make_service()._recovery._connection_factory)
    with pytest.raises(RecoveryConflict, match="ledger is missing|no matching PREPARED"):
        repo.store_snapshot(prepared)


def test_no_snapshot_without_previously_reserved_intent(rig):
    make_service, _ = rig
    prepared = build_prepared()
    with pytest.raises(RecoveryConflict):
        make_service()._recovery.load_snapshot(prepared.preview.operation_id)


def test_second_operation_for_same_manifest_denied(staged):
    _, service, _, _ = staged
    with pytest.raises(IntentConflict, match="already reserved"):
        service.prepare(build_prepared())


def test_snapshot_is_immutable_by_sqlite_trigger(staged):
    prepared, _, _, connect = staged
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with connect() as db:
            db.execute("UPDATE supplier_live_batch_request_snapshots SET payload_sha256='bad'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with connect() as db:
            db.execute("DELETE FROM supplier_live_batch_request_snapshots")


def test_dispatch_journal_immutable_by_sqlite_trigger(staged):
    prepared, service, _, connect = staged
    service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with connect() as db:
            db.execute("UPDATE supplier_live_batch_dispatch_events SET kind='OUTCOME_UNKNOWN'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with connect() as db:
            db.execute("DELETE FROM supplier_live_batch_dispatch_events")


def test_corrupt_snapshot_hash_detected_after_trigger_bypass(staged):
    prepared, service, _, connect = staged
    with connect() as db:
        db.execute("DROP TRIGGER trg_supplier_live_batch_snapshots_no_update")
        db.execute("UPDATE supplier_live_batch_request_snapshots SET payload_json='{}'")
    with pytest.raises(RecoveryConflict, match="SHA-256"):
        service.decision(operation_id=prepared.preview.operation_id)


def test_digest_binding_detects_changed_payload_and_forged_checksum(staged):
    prepared, service, _, connect = staged
    with connect() as db:
        db.execute("DROP TRIGGER trg_supplier_live_batch_snapshots_no_update")
        db.execute("UPDATE supplier_live_batch_request_snapshots SET payload_json='{}', payload_sha256=?", (
            __import__('hashlib').sha256(b'{}').hexdigest(),
        ))
    with pytest.raises(RecoveryConflict, match="snapshot identity"):
        service.decision(operation_id=prepared.preview.operation_id)


def test_mutating_nested_graphql_after_prepare_does_not_change_snapshot(staged):
    prepared, service, _, _ = staged
    originally = service._recovery.load_snapshot(prepared.preview.operation_id)
    prepared.preview.variables["input"]["quantities"][0]["quantity"] += 100
    again = service._recovery.load_snapshot(prepared.preview.operation_id)
    assert again == originally
    with pytest.raises(IntentConflict, match="altered|digest"):
        service.prepare(prepared)


def test_arm_once_is_durable_and_has_exact_digest(staged):
    prepared, service, _, _ = staged
    event = service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    assert event.kind is RecoveryEventKind.DISPATCH_ARMED
    assert event.sequence == 1
    assert event.details == {"request_digest": prepared.request_digest}
    assert service.decision(operation_id=prepared.preview.operation_id).state is RecoveryState.ARMED_OUTCOME_UNCERTAIN


def test_arm_after_restart_is_blocked(staged):
    prepared, service, make_service, _ = staged
    service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    fresh = make_service()  # new object, same durable SQLite file
    assert fresh.decision(operation_id=prepared.preview.operation_id).human_review_required
    with pytest.raises(RecoveryConflict, match="already armed"):
        fresh.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    assert len(fresh._recovery.events(prepared.preview.operation_id)) == 1


@pytest.mark.parametrize("invalid", ["", "f" * 64, None])
def test_arm_wrong_digest_blocked(staged, invalid):
    prepared, service, _, _ = staged
    with pytest.raises(RecoveryConflict, match="digest"):
        service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=invalid)
    assert service.decision(operation_id=prepared.preview.operation_id).event_count == 0


def test_arm_nonexistent_identity_blocked(rig):
    service = rig[0]()
    with pytest.raises(RecoveryConflict):
        service.arm_dispatch(operation_id="not-an-id", request_digest="0" * 64)


def test_unknown_outcome_requires_arming(staged):
    prepared, service, _, _ = staged
    with pytest.raises(RecoveryConflict, match="requires"):
        service.note_outcome_unknown(operation_id=prepared.preview.operation_id)


def test_unknown_outcome_blocks_dispatch_and_retry(staged):
    prepared, service, _, _ = staged
    op = prepared.preview.operation_id
    service.arm_dispatch(operation_id=op, request_digest=prepared.request_digest)
    service.note_outcome_unknown(operation_id=op)
    result = service.decision(operation_id=op)
    assert result.state is RecoveryState.ARMED_OUTCOME_UNCERTAIN
    assert not result.dispatch_allowed and not result.automatic_retry_allowed
    assert result.event_count == 2
    with pytest.raises(RecoveryConflict, match="requires"):
        service.note_outcome_unknown(operation_id=op)


def test_readback_before_arm_blocked(staged):
    prepared, service, _, _ = staged
    with pytest.raises(RecoveryConflict, match="prior armed"):
        service.observe_current_inventory(
            operation_id=prepared.preview.operation_id,
            readback_port=FakeReadback({"1001": 26, "1002": 42}),
        )


@pytest.mark.parametrize("readings,expected", [
    ({"1001": 26, "1002": 42}, RecoveryState.READBACK_TARGET_OBSERVED),
    ({"1001": 25, "1002": 40}, RecoveryState.READBACK_BASELINE_OBSERVED),
    ({"1001": 26, "1002": 40}, RecoveryState.READBACK_MIXED_OR_DIVERGED),
    ({"1001": 25, "1002": 42}, RecoveryState.READBACK_MIXED_OR_DIVERGED),
    ({"1001": 27, "1002": 41}, RecoveryState.READBACK_MIXED_OR_DIVERGED),
])
def test_recovery_readback_classification_never_allows_retry(staged, readings, expected):
    prepared, service, _, _ = staged
    op = prepared.preview.operation_id
    service.arm_dispatch(operation_id=op, request_digest=prepared.request_digest)
    service.note_outcome_unknown(operation_id=op)
    event = service.observe_current_inventory(operation_id=op, readback_port=FakeReadback(readings))
    result = service.decision(operation_id=op)
    assert event.kind is RecoveryEventKind.READBACK_OBSERVED
    assert result.state is expected
    assert result.human_review_required
    assert result.event_count == 3
    assert not result.dispatch_allowed and not result.automatic_retry_allowed


class FailedReadback:
    def read_available(self, *, inventory_item_id, location_id):
        raise ConnectionError("synthetic timeout; do not persist raw exception data")


class WrongReadback(FakeReadback):
    def read_available(self, *, inventory_item_id, location_id):
        state = super().read_available(inventory_item_id=inventory_item_id, location_id=location_id)
        return replace(state, location_id="gid://shopify/Location/111")


class UntrackedReadback(FakeReadback):
    def read_available(self, *, inventory_item_id, location_id):
        state = super().read_available(inventory_item_id=inventory_item_id, location_id=location_id)
        return replace(state, tracked=False)


@pytest.mark.parametrize("port", [
    FailedReadback(), WrongReadback({"1001": 26, "1002": 42}),
    UntrackedReadback({"1001": 26, "1002": 42}), FakeReadback({"1001": True, "1002": 42}),
])
def test_untrusted_or_failed_readback_is_fail_closed(staged, port):
    prepared, service, _, _ = staged
    op = prepared.preview.operation_id
    service.arm_dispatch(operation_id=op, request_digest=prepared.request_digest)
    event = service.observe_current_inventory(operation_id=op, readback_port=port)
    assert event.kind is RecoveryEventKind.READBACK_FAILED
    assert service.decision(operation_id=op).state is RecoveryState.READBACK_FAILED
    assert "synthetic timeout" not in str(event.details)


def test_can_retry_readback_not_mutation_after_failed_check(staged):
    prepared, service, _, _ = staged
    op = prepared.preview.operation_id
    service.arm_dispatch(operation_id=op, request_digest=prepared.request_digest)
    service.observe_current_inventory(operation_id=op, readback_port=FailedReadback())
    service.observe_current_inventory(operation_id=op, readback_port=FakeReadback({"1001": 25, "1002": 40}))
    result = service.decision(operation_id=op)
    assert result.state is RecoveryState.READBACK_BASELINE_OBSERVED
    assert result.event_count == 3
    assert not result.automatic_retry_allowed


def test_event_chain_reconstructs_after_restart(staged):
    prepared, service, make_service, _ = staged
    op = prepared.preview.operation_id
    service.arm_dispatch(operation_id=op, request_digest=prepared.request_digest)
    service.note_outcome_unknown(operation_id=op)
    service.observe_current_inventory(operation_id=op, readback_port=FakeReadback({"1001": 26, "1002": 42}))
    rows = make_service()._recovery.events(op)
    assert [r.sequence for r in rows] == [1, 2, 3]
    assert all(r.previous_hash == (rows[i-1].event_hash if i else "0" * 64) for i, r in enumerate(rows))
    assert all(len(r.event_hash) == 64 for r in rows)


def test_event_chain_tampering_detected(staged):
    prepared, service, _, connect = staged
    op = prepared.preview.operation_id
    service.arm_dispatch(operation_id=op, request_digest=prepared.request_digest)
    with connect() as db:
        db.execute("DROP TRIGGER trg_supplier_live_batch_dispatch_no_update")
        db.execute("UPDATE supplier_live_batch_dispatch_events SET event_hash='bad' WHERE sequence=1")
    with pytest.raises(RecoveryConflict, match="hash chain"):
        service.decision(operation_id=op)


def test_journal_rejects_missing_first_arm(staged):
    prepared, service, _, _ = staged
    with pytest.raises(RecoveryConflict, match="transition"):
        service._recovery.append_event(
            prepared.preview.operation_id, kind=RecoveryEventKind.OUTCOME_UNKNOWN,
            details={"reason": "transport_result_unavailable"}, expected_event_count=0,
        )


def test_journal_rejects_forged_arm_digest(staged):
    prepared, service, _, _ = staged
    with pytest.raises(RecoveryConflict, match="transition"):
        service._recovery.append_event(
            prepared.preview.operation_id, kind=RecoveryEventKind.DISPATCH_ARMED,
            details={"request_digest": "f" * 64}, expected_event_count=0,
        )


def test_journal_rejects_stale_event_count(staged):
    prepared, service, _, _ = staged
    op = prepared.preview.operation_id
    service.arm_dispatch(operation_id=op, request_digest=prepared.request_digest)
    with pytest.raises(RecoveryConflict, match="journal changed"):
        service._recovery.append_event(
            op, kind=RecoveryEventKind.READBACK_FAILED,
            details={"reason": "readback_unavailable_or_untrusted"}, expected_event_count=0,
        )


def test_journal_rejects_bad_event_detail_shape(staged):
    prepared, service, _, _ = staged
    op = prepared.preview.operation_id
    service.arm_dispatch(operation_id=op, request_digest=prepared.request_digest)
    with pytest.raises(RecoveryConflict, match="transition"):
        service._recovery.append_event(
            op, kind=RecoveryEventKind.READBACK_OBSERVED,
            details={"observations": []}, expected_event_count=1,
        )


def test_recovery_snapshot_has_no_authentication_secrets(staged):
    prepared, service, _, _ = staged
    data = service._recovery.load_snapshot(prepared.preview.operation_id).payload
    assert "client_secret" not in str(data).lower()
    assert "access_token" not in str(data).lower()
    assert "idempotencyKey" in str(data)


def test_demo_runs_and_never_calls_real_shopify(capsys):
    from scripts.supplier_batch_recovery_synthetic_demo import main
    assert main() == 0
    output = capsys.readouterr().out
    assert "LIVE SHOPIFY WRITES: 0" in output
    assert "AUTOMATIC RETRY ALLOWED: False" in output
    assert "STATUS: RECOVERY CHECKPOINT VERIFIED" in output


def test_read_only_script_rejects_invalid_location_before_shopify_access():
    from scripts.supplier_live_batch_contract_readonly import main
    with pytest.raises(SystemExit) as exc:
        main(["--location-id", "not-a-gid"])
    assert exc.value.code == 2


def test_real_read_only_cli_unapproved_does_not_authenticate(monkeypatch, capsys):
    """The real CLI PREPARE branch must not authenticate or issue Shopify queries."""
    from scripts import supplier_live_batch_contract_readonly as cli
    from scripts import supplier_live_batch_preflight as old
    from supplier.batch.approval import evaluate_batch_approval
    from supplier.batch.builder import build_batch_safety_manifest
    from supplier.batch.models import BatchSafetyPolicy
    from supplier.decision.models import SupplierSyncDecision, SyncDecisionReason, SyncDecisionStatus
    from supplier.plan.builder import build_dry_run_sync_plan

    # No V1 SQLite access for this test: replace only the baseline builder.
    decisions = [SupplierSyncDecision(
        supplier_code="demo_supplier", supplier_sku=f"SUP-{suffix}",
        shopify_variant_id=f"gid://shopify/ProductVariant/{suffix}",
        shopify_sku=f"DEMO-{suffix}", status=SyncDecisionStatus.ELIGIBLE,
        reason=SyncDecisionReason.INVENTORY_MISMATCH_WITHIN_LIMIT,
        current_inventory_quantity=baseline, supplier_inventory_quantity=after,
        inventory_delta=after - baseline, proposed_inventory_quantity=after,
    ) for suffix, baseline, after in (("1001", 25, 26), ("1002", 40, 42))]
    plan = build_dry_run_sync_plan(decisions)
    manifest = build_batch_safety_manifest(plan=plan, policy=BatchSafetyPolicy())
    monkeypatch.setattr(old, "build_read_only_candidate", lambda: (plan, manifest))

    def forbid_client():
        raise AssertionError("Shopify authentication should be skipped without approval")
    monkeypatch.setattr(old, "build_client", forbid_client)
    assert cli.main(["--location-id", "gid://shopify/Location/999001"]) == 0
    output = capsys.readouterr().out
    assert "SHOPIFY NETWORK CALLS: 0" in output
    assert manifest.manifest_fingerprint in output


def test_real_read_only_cli_approved_only_reads(monkeypatch, capsys):
    """Approved CLI bridges to actual preflight + contract, using fake network adapters."""
    from scripts import supplier_live_batch_contract_readonly as cli
    from scripts import supplier_live_batch_preflight as old
    from scripts.supplier_batch_recovery_synthetic_demo import FakeResolver
    from supplier.batch.approval import evaluate_batch_approval
    from supplier.batch.builder import build_batch_safety_manifest
    from supplier.batch.models import BatchSafetyPolicy
    from supplier.decision.models import SupplierSyncDecision, SyncDecisionReason, SyncDecisionStatus
    from supplier.plan.builder import build_dry_run_sync_plan
    import supplier.execution.readback as readback_module
    import supplier.execution.shopify_adapter as adapter_module

    decisions = [SupplierSyncDecision(
        supplier_code="demo_supplier", supplier_sku=f"SUP-{suffix}",
        shopify_variant_id=f"gid://shopify/ProductVariant/{suffix}",
        shopify_sku=f"DEMO-{suffix}", status=SyncDecisionStatus.ELIGIBLE,
        reason=SyncDecisionReason.INVENTORY_MISMATCH_WITHIN_LIMIT,
        current_inventory_quantity=baseline, supplier_inventory_quantity=after,
        inventory_delta=after - baseline, proposed_inventory_quantity=after,
    ) for suffix, baseline, after in (("1001", 25, 26), ("1002", 40, 42))]
    plan = build_dry_run_sync_plan(decisions)
    manifest = build_batch_safety_manifest(plan=plan, policy=BatchSafetyPolicy())
    assert evaluate_batch_approval(
        plan=plan, manifest=manifest,
        approved_manifest_fingerprint=manifest.manifest_fingerprint,
    ).can_execute
    monkeypatch.setattr(old, "build_read_only_candidate", lambda: (plan, manifest))
    network = {"authenticate": 0, "read": 0, "mutate": 0}

    class FakeClient:
        def graphql(self, query, variables):
            network["mutate"] += 1
            raise AssertionError("GraphQL mutation must never be called by this CLI")

    def fake_build_client():
        network["authenticate"] += 1
        return FakeClient()

    class ReadAdapter(FakeReadback):
        def __init__(self, client):
            assert isinstance(client, FakeClient)
            super().__init__({"1001": 25, "1002": 40})

        def read_available(self, *, inventory_item_id, location_id):
            network["read"] += 1
            return super().read_available(inventory_item_id=inventory_item_id, location_id=location_id)

    monkeypatch.setattr(old, "build_client", fake_build_client)
    monkeypatch.setattr(readback_module, "ShopifyInventoryReadbackAdapter", ReadAdapter)
    monkeypatch.setattr(adapter_module, "SQLiteInventoryTargetResolver", lambda *, location_id: FakeResolver())

    assert cli.main([
        "--location-id", "gid://shopify/Location/999001",
        "--approve-manifest", manifest.manifest_fingerprint,
    ]) == 0
    output = capsys.readouterr().out
    assert network == {"authenticate": 1, "read": 2, "mutate": 0}
    assert "PREFLIGHT: READY" in output
    assert "CAS TARGETS (NOT SENT):" in output
    assert "STATUS: LIVE READ-ONLY BRIDGE READY — EXECUTION DISABLED" in output
