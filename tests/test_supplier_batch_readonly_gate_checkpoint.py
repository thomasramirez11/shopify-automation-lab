"""V2.8B/6 acceptance: strict query fence, live-read safety, immutable recovery."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.supplier_batch_recovery_synthetic_demo import FakeReadback, build_prepared
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive
from supplier.batch.live_readonly_inspection import (
    InspectionStatus, ReadOnlyInspectionRejected,
    inspect_fresh_candidate, inspect_saved_operation,
)
from supplier.batch.live_readonly_query_fence import (
    ReadOnlyQueryRejected, ReadOnlyShopifyQueryFence,
)
from supplier.batch.live_recovery_models import RecoveryConflict
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService
from supplier.batch.live_request_contract import INVENTORY_SET_QUANTITIES
from supplier.execution.readback import (
    INVENTORY_READBACK_QUERY, InventoryReadbackState, ShopifyInventoryReadbackAdapter,
)

ITEM = "gid://shopify/InventoryItem/1001"
LOCATION = "gid://shopify/Location/999001"
VALID_VARIABLES = {"inventoryItemId": ITEM, "locationId": LOCATION}


class DummyGraphQL:
    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else {}

    def graphql(self, query, variables):
        self.calls.append((query, variables))
        return self.result


class ControlledReadback:
    def __init__(self, values=(25, 40), *, wrong=None, failure_at=None):
        self.values = values
        self.wrong = wrong
        self.failure_at = failure_at
        self.calls = 0

    def read_available(self, *, inventory_item_id, location_id):
        self.calls += 1
        if self.failure_at == self.calls:
            raise TimeoutError("secret-shopify-body")
        sku = "DEMO-" + inventory_item_id.rsplit("/", 1)[-1]
        quantity = self.values[self.calls - 1]
        state = InventoryReadbackState(
            inventory_item_id=inventory_item_id,
            sku=sku, tracked=True, location_id=location_id,
            location_name="Synthetic place", location_active=True, level_active=True,
            available_quantity=quantity,
        )
        if self.wrong:
            return replace(state, **self.wrong)
        return state


@pytest.fixture
def prepared():
    return build_prepared()


@pytest.fixture
def archive(tmp_path, prepared):
    db_path = tmp_path / "recovery.sqlite3"

    @contextmanager
    def connection():
        db = sqlite3.connect(db_path)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    service = SupplierLiveBatchRecoveryService(
        intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connection),
        recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connection),
    )
    service.prepare(prepared)
    return db_path, ReadOnlyRecoveryArchive(db_path), service, connection


def test_fence_passes_only_expected_query_and_variables():
    client = DummyGraphQL({"inventoryItem": None})
    fence = ReadOnlyShopifyQueryFence(client)
    variables = dict(VALID_VARIABLES)
    assert fence.graphql(INVENTORY_READBACK_QUERY, variables) == {"inventoryItem": None}
    assert fence.read_queries == 1
    assert client.calls == [(INVENTORY_READBACK_QUERY, VALID_VARIABLES)]
    variables["locationId"] = "changed"
    assert client.calls[0][1]["locationId"] == LOCATION


@pytest.mark.parametrize("query", [
    INVENTORY_SET_QUANTITIES, "mutation { inventorySetQuantities { id } }",
    "query { products(first:1) { nodes { id } } }",
    "{inventoryItem(id: \"1\") { id }}", "", INVENTORY_READBACK_QUERY + " ",
    None, 13,
])
def test_fence_rejects_other_operations_without_network(query):
    client = DummyGraphQL()
    fence = ReadOnlyShopifyQueryFence(client)
    with pytest.raises(ReadOnlyQueryRejected):
        fence.graphql(query, VALID_VARIABLES)
    assert client.calls == [] and fence.read_queries == 0


@pytest.mark.parametrize("variables", [
    None, {}, {"inventoryItemId": ITEM},
    {"inventoryItemId": ITEM, "locationId": LOCATION, "extra": True},
    {"inventoryItemId": ITEM, "locationId": ""},
    {"inventoryItemId": ITEM, "locationId": "gid://shopify/Location/0"},
    {"inventoryItemId": ITEM, "locationId": "gid://shopify/Location/abc"},
    {"inventoryItemId": "gid://shopify/ProductVariant/2", "locationId": LOCATION},
    {"inventoryItemId": "gid://shopify/InventoryItem/0", "locationId": LOCATION},
    {"inventoryItemId": "gid://shopify/InventoryItem/12\nmutation", "locationId": LOCATION},
    {"inventoryItemId": True, "locationId": LOCATION},
    "not a dict",
])
def test_fence_rejects_bad_read_variables(variables):
    client = DummyGraphQL()
    fence = ReadOnlyShopifyQueryFence(client)
    with pytest.raises(ReadOnlyQueryRejected):
        fence.graphql(INVENTORY_READBACK_QUERY, variables)
    assert fence.read_queries == 0 and not client.calls


def test_fence_rejects_missing_client_and_no_mutation_interface():
    with pytest.raises(ReadOnlyQueryRejected):
        ReadOnlyShopifyQueryFence(object())
    assert not hasattr(ReadOnlyShopifyQueryFence(DummyGraphQL()), "send")


def test_actual_shopify_adapter_can_use_fenced_query():
    client = DummyGraphQL({"inventoryItem": {
        "id": ITEM, "sku": "DEMO-1001", "tracked": True,
        "inventoryLevel": {"isActive": True, "location": {
            "id": LOCATION, "name": "Synthetic place", "isActive": True,
        }, "quantities": [{"name": "available", "quantity": 25}]},
    }})
    fence = ReadOnlyShopifyQueryFence(client)
    state = ShopifyInventoryReadbackAdapter(fence).read_available(
        inventory_item_id=ITEM, location_id=LOCATION)
    assert state.available_quantity == 25
    assert fence.read_queries == 1
    assert client.calls[0][0] == INVENTORY_READBACK_QUERY


@pytest.mark.parametrize("values,expected", [
    ((25, 40), InspectionStatus.BASELINES_MATCH),
    ((26, 42), InspectionStatus.STALE),
    ((25, 39), InspectionStatus.STALE),
    ((18, 40), InspectionStatus.STALE),
    ((40, 25), InspectionStatus.STALE),
])
def test_fresh_candidate_classifies_realistic_inventory(prepared, values, expected):
    port = ControlledReadback(values)
    report = inspect_fresh_candidate(prepared, readback_port=port)
    assert report.status == expected
    assert report.successful_reads == 2
    assert len(report.items) == 2
    assert report.can_continue_to_operator_review is (expected == InspectionStatus.BASELINES_MATCH)
    assert report.live_execution_allowed is False and report.automatic_retry_allowed is False


@pytest.mark.parametrize("wrong", [
    {"sku": "OTHER"}, {"inventory_item_id": "gid://shopify/InventoryItem/998"},
    {"location_id": "gid://shopify/Location/56"},
    {"tracked": False}, {"location_active": False}, {"level_active": False},
    {"available_quantity": True}, {"available_quantity": -1},
    {"available_quantity": "25"}, {"available_quantity": None},
])
def test_integrity_failure_blocks_fresh_candidate(prepared, wrong):
    result = inspect_fresh_candidate(prepared, readback_port=ControlledReadback(wrong=wrong))
    assert result.status is InspectionStatus.BLOCKED
    assert result.human_review_required is True
    assert result.successful_reads == 0
    assert result.live_execution_allowed is False


@pytest.mark.parametrize("failure_at,expected_reads", [(1, 0), (2, 1)])
def test_partial_network_failure_blocks_all(prepared, failure_at, expected_reads):
    result = inspect_fresh_candidate(prepared, readback_port=ControlledReadback(failure_at=failure_at))
    assert result.status == InspectionStatus.BLOCKED
    assert result.successful_reads == expected_reads
    assert not result.can_continue_to_operator_review
    assert "secret-shopify" not in str(result)


def test_candidate_tampered_nested_quantities_blocked_before_read(prepared):
    prepared.preview.variables["input"]["quantities"][0]["quantity"] += 2
    port = ControlledReadback()
    with pytest.raises(ValueError):
        inspect_fresh_candidate(prepared, readback_port=port)
    assert port.calls == 0


def test_readonly_archive_loads_snapshot_and_events(archive, prepared):
    path, reader, service, _ = archive
    before = path.read_bytes()
    snapshot, events = reader.load_verified(prepared.preview.operation_id)
    assert snapshot.operation_id == prepared.preview.operation_id
    assert snapshot.payload["query"] == INVENTORY_SET_QUANTITIES
    assert events == ()
    assert path.read_bytes() == before
    assert inspect_saved_operation(archive=reader, operation_id=prepared.preview.operation_id,
                                   readback_port=ControlledReadback()).status == InspectionStatus.BASELINES_MATCH
    assert path.read_bytes() == before


def test_armed_target_does_not_authorize_retry_or_execution(archive, prepared):
    path, reader, service, _ = archive
    service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    before = path.read_bytes()
    report = inspect_saved_operation(archive=reader, operation_id=prepared.preview.operation_id,
                                     readback_port=ControlledReadback((26, 42)))
    assert report.status == InspectionStatus.RECOVERY_TARGET_OBSERVED
    assert report.dispatch_event_count == 1
    assert report.human_review_required
    assert not report.can_continue_to_operator_review
    assert not report.live_execution_allowed and not report.automatic_retry_allowed
    assert path.read_bytes() == before


@pytest.mark.parametrize("quantities,expected", [
    ((25, 40), InspectionStatus.RECOVERY_BASELINE_OBSERVED),
    ((25, 42), InspectionStatus.RECOVERY_MIXED_OR_DIVERGED),
    ((26, 40), InspectionStatus.RECOVERY_MIXED_OR_DIVERGED),
    ((15, 31), InspectionStatus.RECOVERY_MIXED_OR_DIVERGED),
])
def test_armed_recovery_classifies_without_writes(archive, prepared, quantities, expected):
    _, reader, service, _ = archive
    service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    report = inspect_saved_operation(archive=reader, operation_id=prepared.preview.operation_id,
                                     readback_port=ControlledReadback(quantities))
    assert report.status == expected
    assert report.human_review_required
    assert not report.can_continue_to_operator_review
    assert not report.live_execution_allowed


def test_unarmed_changed_quantity_requires_new_plan(archive, prepared):
    _, reader, _, _ = archive
    report = inspect_saved_operation(archive=reader, operation_id=prepared.preview.operation_id,
                                     readback_port=ControlledReadback((25, 42)))
    assert report.status is InspectionStatus.STALE
    assert not report.can_continue_to_operator_review


def test_armed_broken_readback_still_never_retries(archive, prepared):
    _, reader, service, _ = archive
    service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    report = inspect_saved_operation(archive=reader, operation_id=prepared.preview.operation_id,
                                     readback_port=ControlledReadback(failure_at=2))
    assert report.status is InspectionStatus.BLOCKED
    assert report.dispatch_event_count == 1
    assert report.human_review_required
    assert not report.automatic_retry_allowed


def test_snapshot_tampering_blocks_before_network(archive, prepared):
    _, reader, _, connect = archive
    with connect() as db:
        db.execute("DROP TRIGGER trg_supplier_live_batch_snapshots_no_update")
        db.execute("UPDATE supplier_live_batch_request_snapshots SET payload_json='{}' WHERE operation_id=?",
                   (prepared.preview.operation_id,))
    port = ControlledReadback()
    with pytest.raises(RecoveryConflict):
        inspect_saved_operation(archive=reader, operation_id=prepared.preview.operation_id, readback_port=port)
    assert port.calls == 0


def test_hash_chain_tampering_blocks_before_network(archive, prepared):
    _, reader, service, connect = archive
    service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    with connect() as db:
        db.execute("DROP TRIGGER trg_supplier_live_batch_dispatch_no_update")
        db.execute("UPDATE supplier_live_batch_dispatch_events SET event_hash='BAD' WHERE operation_id=?",
                   (prepared.preview.operation_id,))
    port = ControlledReadback()
    with pytest.raises(RecoveryConflict):
        inspect_saved_operation(archive=reader, operation_id=prepared.preview.operation_id, readback_port=port)
    assert port.calls == 0


def test_invalid_uuid_is_rejected_before_network(archive):
    _, reader, _, _ = archive
    with pytest.raises(RecoveryConflict):
        reader.load_verified("not-a-uuid")


def test_invalid_archive_path_does_not_create_file(tmp_path):
    path = tmp_path / "nonexistent.sqlite3"
    with pytest.raises(OSError):
        ReadOnlyRecoveryArchive(path)
    assert not path.exists()


def test_archive_always_requires_explicit_source_path():
    with pytest.raises(TypeError):
        ReadOnlyRecoveryArchive()


def test_readonly_archive_cannot_be_used_to_mutate_database(archive, prepared):
    path, _, _, _ = archive
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM supplier_live_batch_intents")


def test_archive_inspector_rejects_unverified_snapshot_or_events(prepared):
    port = ControlledReadback()
    with pytest.raises(ReadOnlyInspectionRejected):
        inspect_saved_operation(archive=object(), operation_id=prepared.preview.operation_id,
                                readback_port=port)
    assert port.calls == 0


def test_demo_runtime_offline(capsys):
    from scripts.supplier_batch_readonly_gate_synthetic_demo import main
    assert main() == 0
    output = capsys.readouterr().out
    assert "BASELINES_MATCH" in output
    assert "STALE" in output
    assert "RECOVERY_TARGET_OBSERVED" in output
    assert "LIVE SHOPIFY WRITES: 0" in output
    assert "EXECUTION DISABLED" in output

@pytest.mark.parametrize("field,value", [
    ("tracked", "false"), ("tracked", None), ("tracked", 1),
    ("tracked", 0), ("level", "false"), ("level", None),
    ("location", "true"), ("location", None),
])
def test_fence_rejects_truthy_boolean_coercion(field, value):
    item = {"id": ITEM, "sku": "DEMO-1001", "tracked": True,
            "inventoryLevel": {"isActive": True, "location": {
                "id": LOCATION, "name": "A", "isActive": True},
                "quantities": [{"name": "available", "quantity": 25}]}}
    if field == "tracked":
        item["tracked"] = value
    elif field == "level":
        item["inventoryLevel"]["isActive"] = value
    else:
        item["inventoryLevel"]["location"]["isActive"] = value
    fence = ReadOnlyShopifyQueryFence(DummyGraphQL({"inventoryItem": item}))
    with pytest.raises(ReadOnlyQueryRejected, match="Boolean"):
        ShopifyInventoryReadbackAdapter(fence).read_available(
            inventory_item_id=ITEM, location_id=LOCATION)
    assert fence.read_queries == 1


def _synthetic_plan_manifest():
    from supplier.batch.builder import build_batch_safety_manifest
    from supplier.batch.models import BatchSafetyPolicy
    from supplier.decision.models import SupplierSyncDecision, SyncDecisionReason, SyncDecisionStatus
    from supplier.plan.builder import build_dry_run_sync_plan
    decisions = [
        SupplierSyncDecision(
            supplier_code="demo_supplier", supplier_sku=f"SUP-{suffix}",
            shopify_variant_id=f"gid://shopify/ProductVariant/{suffix}",
            shopify_sku=f"DEMO-{suffix}", status=SyncDecisionStatus.ELIGIBLE,
            reason=SyncDecisionReason.INVENTORY_MISMATCH_WITHIN_LIMIT,
            current_inventory_quantity=baseline,
            supplier_inventory_quantity=proposed,
            inventory_delta=proposed-baseline, proposed_inventory_quantity=proposed,
        )
        for suffix, baseline, proposed in (("1001", 25, 26), ("1002", 40, 42))
    ]
    plan = build_dry_run_sync_plan(decisions)
    return plan, build_batch_safety_manifest(plan=plan, policy=BatchSafetyPolicy())


def test_readonly_live_controller_requires_approval_before_shopify_network(monkeypatch, capsys):
    from scripts import supplier_batch_readonly_gate as cli
    from scripts import supplier_live_batch_preflight as prior
    plan, manifest = _synthetic_plan_manifest()
    monkeypatch.setattr(prior, "build_read_only_candidate", lambda: (plan, manifest))
    monkeypatch.setattr(prior, "build_client", lambda: (_ for _ in ()).throw(AssertionError("no network")))
    assert cli.main(["--location-id", LOCATION]) == 0
    output = capsys.readouterr().out
    assert "APPROVAL STATUS: APPROVAL_REQUIRED" in output
    assert "LIVE SHOPIFY INVENTORY READS: 0" in output
    assert "LIVE SHOPIFY WRITES: 0" in output


def test_readonly_live_controller_fenced_queries_with_fake_responses(monkeypatch, capsys):
    from scripts import supplier_batch_readonly_gate as cli
    from scripts import supplier_live_batch_preflight as prior
    from supplier.execution import shopify_adapter
    from scripts.supplier_batch_recovery_synthetic_demo import FakeResolver
    plan, manifest = _synthetic_plan_manifest()
    monkeypatch.setattr(prior, "build_read_only_candidate", lambda: (plan, manifest))
    monkeypatch.setattr(shopify_adapter, "SQLiteInventoryTargetResolver", lambda location_id: FakeResolver())

    class FakeClient:
        def __init__(self):
            self.calls = 0
        def graphql(self, query, variables):
            assert query == INVENTORY_READBACK_QUERY
            self.calls += 1
            item_id = variables["inventoryItemId"]
            quantity = 25 if item_id.endswith("1001") else 40
            return {"inventoryItem": {
                "id": item_id, "sku": "DEMO-" + item_id.rsplit("/", 1)[-1],
                "tracked": True,
                "inventoryLevel": {"isActive": True,
                    "location": {"id": LOCATION, "name": "Synthetic", "isActive": True},
                    "quantities": [{"name": "available", "quantity": quantity}]},
            }}

    client = FakeClient()
    monkeypatch.setattr(prior, "build_client", lambda: client)
    assert cli.main(["--location-id", LOCATION,
                     "--approve-manifest", manifest.manifest_fingerprint]) == 0
    output = capsys.readouterr().out
    assert "SECOND READ STATUS: BASELINES_MATCH" in output
    assert "LIVE SHOPIFY INVENTORY READS: 4" in output
    assert "LIVE EXECUTION ALLOWED: False" in output
    assert "PROJECT SQLITE WRITES: 0" in output
    assert client.calls == 4  # V2.8A fresh preflight + independent recheck


def test_readonly_live_controller_detects_drift_after_preflight(monkeypatch, capsys):
    from scripts import supplier_batch_readonly_gate as cli
    from scripts import supplier_live_batch_preflight as prior
    from supplier.execution import shopify_adapter
    from scripts.supplier_batch_recovery_synthetic_demo import FakeResolver
    plan, manifest = _synthetic_plan_manifest()
    monkeypatch.setattr(prior, "build_read_only_candidate", lambda: (plan, manifest))
    monkeypatch.setattr(shopify_adapter, "SQLiteInventoryTargetResolver", lambda location_id: FakeResolver())

    class DriftingClient:
        def __init__(self):
            self.calls = 0
        def graphql(self, query, variables):
            self.calls += 1
            item_id = variables["inventoryItemId"]
            fresh = 39 if self.calls == 4 else (25 if item_id.endswith("1001") else 40)
            return {"inventoryItem": {"id": item_id,
                "sku": "DEMO-" + item_id.rsplit("/", 1)[-1], "tracked": True,
                "inventoryLevel": {"isActive": True, "location": {
                    "id": LOCATION, "name": "Synthetic", "isActive": True},
                    "quantities": [{"name": "available", "quantity": fresh}]}}}

    client = DriftingClient()
    monkeypatch.setattr(prior, "build_client", lambda: client)
    assert cli.main(["--location-id", LOCATION,
                     "--approve-manifest", manifest.manifest_fingerprint]) == 2
    output = capsys.readouterr().out
    assert "SECOND READ STATUS: STALE" in output
    assert "NO DISPATCH" in output
    assert "LIVE EXECUTION ALLOWED: False" in output
    assert client.calls == 4


def test_recovery_cli_reads_archive_without_network_when_not_requested(monkeypatch, archive, prepared, capsys):
    from scripts import supplier_batch_recovery_inspect_readonly as cli
    from scripts import supplier_live_batch_preflight as prior
    monkeypatch.setattr(prior, "build_client", lambda: (_ for _ in ()).throw(AssertionError("must not authenticate")))
    path, _, _, _ = archive
    assert cli.main(["--database-file", str(path),
                     "--operation-id", prepared.preview.operation_id]) == 0
    output = capsys.readouterr().out
    assert "INVENTORY READBACK ENABLED: False" in output
    assert "LIVE SHOPIFY NETWORK CALLS: 0" in output
    assert "MUTATIONS: DISABLED" in output
