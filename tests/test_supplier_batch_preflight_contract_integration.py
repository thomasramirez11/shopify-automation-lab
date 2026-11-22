"""V2.8B/2 acceptance tests. All Shopify I/O is replaced with synthetic ports."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

import pytest

from supplier.batch.approval import evaluate_batch_approval
from supplier.batch.builder import build_batch_safety_manifest
from supplier.batch.live_intent_repository import IntentConflict, SupplierLiveBatchIntentRepository
from supplier.batch.live_preflight_bridge import prepare_from_fresh_preflight
from supplier.batch.live_request_contract import ContractRejected
from supplier.batch.models import BatchSafetyPolicy
from supplier.decision.models import SupplierSyncDecision, SyncDecisionReason, SyncDecisionStatus
from supplier.execution.models import SupplierExecutionError
from supplier.execution.readback import InventoryReadbackState
from dataclasses import dataclass

@dataclass(frozen=True)
class ShopifyInventoryTarget:
    inventory_item_id: str
    location_id: str
from supplier.plan.builder import build_dry_run_sync_plan

LOCATION = "gid://shopify/Location/999001"


class Resolver:
    def __init__(self, *, location=LOCATION, missing=False):
        self.location, self.missing = location, missing
        self.calls = 0

    def resolve(self, shopify_variant_id):
        self.calls += 1
        if self.missing:
            return None
        return ShopifyInventoryTarget(
            inventory_item_id="gid://shopify/InventoryItem/" + shopify_variant_id.rsplit("/", 1)[-1],
            location_id=self.location,
        )


class Readback:
    def __init__(self, *, changed=None, tracked=True, sku_changed=False, fail=False):
        self.changed = changed or {}
        self.tracked, self.sku_changed, self.fail = tracked, sku_changed, fail
        self.calls = 0

    def read_available(self, *, inventory_item_id, location_id):
        self.calls += 1
        if self.fail:
            raise SupplierExecutionError("synthetic failed live read")
        suffix = inventory_item_id.rsplit("/", 1)[-1]
        return InventoryReadbackState(
            inventory_item_id=inventory_item_id,
            sku=f"{'WRONG' if self.sku_changed else 'DEMO'}-{suffix}",
            tracked=self.tracked, location_id=location_id,
            location_name="Fake location", location_active=True, level_active=True,
            available_quantity=self.changed.get(suffix, {"1001": 25, "1002": 40}[suffix]),
        )


def build_bundle():
    decisions = [
        SupplierSyncDecision(
            supplier_code="demo_supplier", supplier_sku=f"SUP-{suffix}",
            shopify_variant_id=f"gid://shopify/ProductVariant/{suffix}",
            shopify_sku=f"DEMO-{suffix}",
            status=SyncDecisionStatus.ELIGIBLE,
            reason=SyncDecisionReason.INVENTORY_MISMATCH_WITHIN_LIMIT,
            current_inventory_quantity=current,
            supplier_inventory_quantity=proposed,
            inventory_delta=proposed - current,
            proposed_inventory_quantity=proposed,
        )
        for suffix, current, proposed in (("1001", 25, 26), ("1002", 40, 42))
    ]
    plan = build_dry_run_sync_plan(decisions)
    manifest = build_batch_safety_manifest(plan=plan, policy=BatchSafetyPolicy())
    approval = evaluate_batch_approval(
        plan=plan, manifest=manifest, approved_manifest_fingerprint=manifest.manifest_fingerprint
    )
    return plan, manifest, approval


def prepare(bundle=None, resolver=None, readback=None):
    plan, manifest, approval = bundle or build_bundle()
    return prepare_from_fresh_preflight(
        plan=plan, manifest=manifest, approval_report=approval,
        target_resolver=resolver or Resolver(),
        readback_port=readback or Readback(), expected_location_id=LOCATION,
    )


@pytest.fixture
def repository(tmp_path):
    db_path = tmp_path / "temporary_intents.sqlite3"

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

    return SupplierLiveBatchIntentRepository(connection_factory=connection), connection


def test_integrates_actual_preflight_service_and_contract():
    readback = Readback()
    result = prepare(readback=readback)
    assert readback.calls == 2
    assert result.preflight.ready_items == 2
    assert result.preview.mode == "OFFLINE_PREVIEW_ONLY"
    assert result.mode == "OFFLINE_PREVIEW_ONLY"
    assert result.preview.variables["idempotencyKey"] == result.preview.operation_id
    assert len(result.preview.variables["input"]["quantities"]) == 2
    assert not hasattr(result, "execute")


def test_cas_comes_from_actual_fresh_readback():
    result = prepare()
    quantities = result.preview.variables["input"]["quantities"]
    assert [(q["changeFromQuantity"], q["quantity"]) for q in quantities] == [(25, 26), (40, 42)]
    assert all(q["changeFromQuantity"] is not None for q in quantities)


def test_audit_batch_id_matches_existing_ledger_formula():
    result = prepare()
    import hashlib
    assert result.batch_id == hashlib.sha256(
        ("supplier-batch:" + result.manifest_fingerprint).encode("utf-8")
    ).hexdigest()


def test_digest_is_bound_to_the_generated_operation_id():
    first = prepare()
    second = prepare()
    assert first.preview.operation_id != second.preview.operation_id
    assert first.request_digest != second.request_digest
    assert first.preflight_fingerprint == second.preflight_fingerprint


@pytest.mark.parametrize("changed", [{"1001": 24}, {"1002": 39}, {"1001": 26}, {"1002": 41}])
def test_stale_readback_blocks_entire_batch(changed):
    with pytest.raises(ContractRejected, match="not READY"):
        prepare(readback=Readback(changed=changed))


@pytest.mark.parametrize("kwargs", [{"tracked": False}, {"sku_changed": True}, {"fail": True}])
def test_blocked_readback_prevents_contract(kwargs):
    with pytest.raises(ContractRejected, match="not READY"):
        prepare(readback=Readback(**kwargs))


def test_missing_inventory_item_blocks_contract():
    with pytest.raises(ContractRejected, match="not READY"):
        prepare(resolver=Resolver(missing=True))


def test_wrong_location_blocks_contract():
    with pytest.raises(ContractRejected, match="not READY"):
        prepare(resolver=Resolver(location="gid://shopify/Location/999002"))


def test_unapproved_manifest_rejected_before_network_reads():
    plan, manifest, _ = build_bundle()
    approval = evaluate_batch_approval(plan=plan, manifest=manifest, approved_manifest_fingerprint=None)
    readback = Readback()
    with pytest.raises(ContractRejected, match="human approval"):
        prepare((plan, manifest, approval), readback=readback)
    assert readback.calls == 0


def test_changed_manifest_approval_rejected():
    plan, manifest, _ = build_bundle()
    approval = evaluate_batch_approval(plan=plan, manifest=manifest, approved_manifest_fingerprint="f" * 64)
    with pytest.raises(ContractRejected, match="human approval"):
        prepare((plan, manifest, approval))


def test_tampered_manifest_without_new_fingerprint_fails_closed():
    plan, manifest, approval = build_bundle()
    changed_item = replace(manifest.mutations[0], proposed_inventory_quantity=27, inventory_delta=2)
    malformed = replace(manifest, mutations=(changed_item, manifest.mutations[1]))
    with pytest.raises(ContractRejected, match="manifest changed"):
        prepare((plan, malformed, approval))


def test_batch_too_large_for_live_contract_rejected():
    plan, manifest, approval = build_bundle()
    changed_item = replace(manifest.mutations[0], proposed_inventory_quantity=29, inventory_delta=4)
    malformed = replace(manifest, mutations=(changed_item, manifest.mutations[1]))
    with pytest.raises(Exception):
        prepare((plan, malformed, approval))


def test_intent_reservation_persists_uuid_and_payload(repository):
    store, connection = repository
    result = prepare()
    stored = store.reserve(result)
    assert stored.operation_id == result.preview.operation_id
    assert stored.status == "PREPARED"
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM supplier_live_batch_intents").fetchone()[0] == 1
        assert db.execute("SELECT request_digest FROM supplier_live_batch_intents").fetchone()[0] == result.request_digest


def test_same_identity_is_idempotent(repository):
    store, connection = repository
    result = prepare()
    assert store.reserve(result) == store.reserve(result)
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM supplier_live_batch_intents").fetchone()[0] == 1


def test_manifest_cannot_be_rereserved_with_new_uuid(repository):
    store, _ = repository
    store.reserve(prepare())
    with pytest.raises(IntentConflict, match="already reserved"):
        store.reserve(prepare())


def test_uuid_reuse_with_different_payload_fails(repository):
    store, _ = repository
    result = prepare()
    store.reserve(result)
    with pytest.raises(IntentConflict, match="request digest mismatch"):
        store.reserve(replace(result, request_digest="a" * 64))


def test_uuid_reuse_with_wrong_manifest_fails(repository):
    store, _ = repository
    result = prepare()
    store.reserve(result)
    with pytest.raises(IntentConflict, match="preflight evidence"):
        store.reserve(replace(result, manifest_fingerprint="c" * 64))


def test_reservation_rejects_wrong_object(repository):
    store, _ = repository
    with pytest.raises(IntentConflict, match="PreparedBatchRequest"):
        store.reserve({"hello": "world"})


def test_reservation_rejects_wrong_mode(repository):
    store, _ = repository
    with pytest.raises(IntentConflict, match="offline previews"):
        store.reserve(replace(prepare(), mode="EXECUTE"))


def test_reservation_rejects_invalid_hash(repository):
    store, _ = repository
    with pytest.raises(IntentConflict, match="invalid request_digest"):
        store.reserve(replace(prepare(), request_digest="invalid"))


def test_reservation_rejects_bad_uuid(repository):
    store, _ = repository
    result = prepare()
    with pytest.raises(IntentConflict, match="UUIDv4"):
        store.reserve(replace(result, preview=replace(result.preview, operation_id=str(uuid4()).upper())))


@pytest.mark.parametrize("command", [
    "UPDATE supplier_live_batch_intents SET status = 'PREPARED'",
    "DELETE FROM supplier_live_batch_intents",
])
def test_append_only_database_triggers_enforced(repository, command):
    store, connection = repository
    store.reserve(prepare())
    with pytest.raises(sqlite3.DatabaseError):
        with connection() as db:
            db.execute(command)


def test_reservation_never_calls_shopify_or_mutations(repository):
    store, connection = repository
    # No Shopify client/SDK passed to reserve(); it only accepts immutable prepared data.
    result = prepare()
    store.reserve(result)
    with connection() as db:
        assert db.execute("SELECT status FROM supplier_live_batch_intents").fetchone()[0] == "PREPARED"


def test_reservation_rejects_tampered_nested_cas(repository):
    store, _ = repository
    result = prepare()
    result.preview.variables["input"]["quantities"][0]["changeFromQuantity"] = None
    with pytest.raises(IntentConflict, match="mutation preview was altered"):
        store.reserve(result)


def test_reservation_rejects_tampered_proposed_quantity(repository):
    store, _ = repository
    result = prepare()
    result.preview.variables["input"]["quantities"][0]["quantity"] = 300
    with pytest.raises(IntentConflict, match="mutation preview was altered"):
        store.reserve(result)


def test_reservation_rejects_mismatched_batch_id(repository):
    store, _ = repository
    with pytest.raises(IntentConflict, match="batch audit identity"):
        store.reserve(replace(prepare(), batch_id="b" * 64))


def test_reject_tampered_plan_fingerprint_with_canonical_manifest():
    plan, _, _ = build_bundle()
    changed = replace(plan.items[0], current_inventory_quantity=24, inventory_delta=2)
    bad_plan = replace(plan, items=(changed, plan.items[1]))
    bad_manifest = build_batch_safety_manifest(plan=bad_plan, policy=BatchSafetyPolicy())
    bad_approval = evaluate_batch_approval(
        plan=bad_plan, manifest=bad_manifest,
        approved_manifest_fingerprint=bad_manifest.manifest_fingerprint,
    )
    with pytest.raises(ContractRejected, match="source plan fingerprint"):
        prepare((bad_plan, bad_manifest, bad_approval))
