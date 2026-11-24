"""V2.8B/5 acceptance: fake Shopify responses, durable journal, no live I/O."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from scripts.supplier_batch_recovery_synthetic_demo import build_prepared
from supplier.batch.live_fake_receipt_repository import SupplierLiveBatchFakeReceiptRepository
from supplier.batch.live_fake_sender import ScriptedFakeShopifyTransport, SupplierLiveBatchFakeSender
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository
from supplier.batch.live_recovery_models import RecoveryConflict, RecoveryState
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService
from supplier.batch.live_response_policy import (
    ResponseAssessment, SimulatedResponseStatus, classify_shopify_response,
)


@pytest.fixture
def rig(tmp_path):
    path = tmp_path / "fake_only.sqlite3"

    @contextmanager
    def connect():
        db = sqlite3.connect(path)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def service():
        return SupplierLiveBatchRecoveryService(
            intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connect),
            recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connect),
        )

    def receipts():
        return SupplierLiveBatchFakeReceiptRepository(connection_factory=connect)

    prepared = build_prepared()
    service().prepare(prepared)
    return prepared, connect, service, receipts


def success_response(prepared):
    return {"data": {"inventorySetQuantities": {
        "userErrors": [],
        "inventoryAdjustmentGroup": {
            "reason": "Inventory correction",
            "referenceDocumentUri": prepared.preview.variables["input"]["referenceDocumentUri"],
            "changes": [
                {"name": "available", "delta": 1, "quantityAfterChange": None},
                {"name": "on_hand", "delta": 1, "quantityAfterChange": None},
                {"name": "available", "delta": 2, "quantityAfterChange": None},
            ],
        },
    }}}


def user_error_response(_prepared):
    return {"data": {"inventorySetQuantities": {
        "userErrors": [{"code": "COMPARE_QUANTITY_STALE", "field": ["input"],
                        "message": "Simulated rejection"}],
        "inventoryAdjustmentGroup": None,
    }}}


def _sender(rig):
    _, _, make_service, make_receipts = rig
    return SupplierLiveBatchFakeSender(recovery_service=make_service(), receipt_repository=make_receipts())


def _send(rig, response):
    prepared, _, _, _ = rig
    fake = ScriptedFakeShopifyTransport(response)
    return _sender(rig).send_once(operation_id=prepared.preview.operation_id, transport=fake), fake


def _events(rig):
    prepared, _, make_service, _ = rig
    return make_service()._recovery.events(prepared.preview.operation_id)


def _receipt(rig):
    prepared, _, make_service, make_receipts = rig
    return make_receipts().load(recovery_repository=make_service()._recovery,
                                operation_id=prepared.preview.operation_id)


def test_acknowledged_response_never_verifies_inventory(rig):
    prepared = rig[0]
    result, fake = _send(rig, success_response(prepared))
    assert result.assessment.status is SimulatedResponseStatus.ACKNOWLEDGED_NEEDS_READBACK
    assert not result.assessment.inventory_verified
    assert not result.assessment.automatic_retry_allowed
    assert (result.network_calls, result.live_shopify_writes) == (0, 0)
    assert fake.calls == 1
    assert len(_events(rig)) == 1
    assert _receipt(rig) == result.receipt
    assert rig[2]().decision(operation_id=prepared.preview.operation_id).state is RecoveryState.ARMED_OUTCOME_UNCERTAIN


def test_user_errors_require_review(rig):
    result, fake = _send(rig, user_error_response(rig[0]))
    assert fake.calls == 1
    assert result.assessment.status is SimulatedResponseStatus.USER_ERRORS_REQUIRE_REVIEW
    assert len(_events(rig)) == 1
    assert "Simulated rejection" not in str(result.receipt)


@pytest.mark.parametrize("failure", [TimeoutError("secret timeout body"), ConnectionError("secret"), RuntimeError("secret")])
def test_exception_is_unknown_and_sanitized(rig, failure):
    result, fake = _send(rig, failure)
    assert fake.calls == 1
    assert result.assessment.status is SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW
    assert result.assessment.reason_code == "TRANSPORT_EXCEPTION_OUTCOME_UNKNOWN"
    assert len(_events(rig)) == 2
    assert "secret" not in str(result.receipt)
    assert rig[2]().decision(operation_id=rig[0].preview.operation_id).automatic_retry_allowed is False


def test_failure_to_persist_response_does_not_allow_replay(rig):
    prepared, connect, make_service, make_receipts = rig
    with connect() as db:
        make_receipts()._initialize(db)
        db.executescript("""CREATE TRIGGER fail_fake_receipt BEFORE INSERT ON supplier_live_batch_fake_receipts
            BEGIN SELECT RAISE(ABORT, 'simulated disk fault'); END;""")
    fake = ScriptedFakeShopifyTransport(success_response(prepared))
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        _sender(rig).send_once(operation_id=prepared.preview.operation_id, transport=fake)
    assert fake.calls == 1
    assert len(_events(rig)) == 1
    with pytest.raises(RecoveryConflict, match="already dispatched"):
        _sender(rig).send_once(operation_id=prepared.preview.operation_id, transport=fake)
    assert fake.calls == 1
    assert make_service().decision(operation_id=prepared.preview.operation_id).automatic_retry_allowed is False


def test_keyboard_interrupt_simulated_crash_keeps_durable_arm_and_prevents_replay(rig):
    prepared = rig[0]
    fake = ScriptedFakeShopifyTransport(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        _sender(rig).send_once(operation_id=prepared.preview.operation_id, transport=fake)
    assert len(_events(rig)) == 1
    assert rig[2]().decision(operation_id=prepared.preview.operation_id).state is RecoveryState.ARMED_OUTCOME_UNCERTAIN
    with pytest.raises(RecoveryConflict):
        _sender(rig).send_once(operation_id=prepared.preview.operation_id, transport=fake)
    assert fake.calls == 1


def test_second_send_blocked_even_after_valid_receipt(rig):
    prepared = rig[0]
    fake = ScriptedFakeShopifyTransport(success_response(prepared))
    _sender(rig).send_once(operation_id=prepared.preview.operation_id, transport=fake)
    with pytest.raises(RecoveryConflict, match="already dispatched"):
        _sender(rig).send_once(operation_id=prepared.preview.operation_id, transport=fake)
    assert fake.calls == 1


def test_real_client_like_port_is_rejected_before_arm(rig):
    class NotTheScriptedFake:
        def send(self, query, variables):
            raise AssertionError("real send must never be invoked")
    with pytest.raises(RecoveryConflict, match="ONLY"):
        _sender(rig).send_once(operation_id=rig[0].preview.operation_id,
                               transport=NotTheScriptedFake())
    assert not _events(rig)


def test_fake_transport_subclass_rejected_before_arm(rig):
    class Bypass(ScriptedFakeShopifyTransport):
        pass
    with pytest.raises(RecoveryConflict, match="ONLY"):
        _sender(rig).send_once(operation_id=rig[0].preview.operation_id,
                               transport=Bypass(success_response(rig[0])))
    assert not _events(rig)


def test_missing_atomic_preparation_rejected_without_fake_send(rig):
    fake = ScriptedFakeShopifyTransport(success_response(rig[0]))
    with pytest.raises(RecoveryConflict):
        _sender(rig).send_once(operation_id="not-an-operation", transport=fake)
    assert fake.calls == 0


def test_recovery_factory_mismatch_rejected(rig, tmp_path):
    _, _, make_service, _ = rig
    @contextmanager
    def other_connection():
        db = sqlite3.connect(tmp_path / "other.sqlite")
        try:
            yield db
            db.commit()
        finally:
            db.close()
    with pytest.raises(RecoveryConflict, match="one SQLite"):
        SupplierLiveBatchFakeSender(
            recovery_service=make_service(),
            receipt_repository=SupplierLiveBatchFakeReceiptRepository(connection_factory=other_connection),
        )


def test_sent_request_copied_and_matches_immutable_snapshot(rig):
    prepared, _, make_service, _ = rig
    fake = ScriptedFakeShopifyTransport(success_response(prepared))
    _sender(rig).send_once(operation_id=prepared.preview.operation_id, transport=fake)
    snapshot = make_service()._recovery.load_snapshot(prepared.preview.operation_id)
    assert fake.sent_queries == [snapshot.payload["query"]]
    assert fake.sent_variables == [snapshot.payload["variables"]]
    assert fake.sent_variables[0]["idempotencyKey"] == prepared.preview.operation_id
    assert [x["changeFromQuantity"] for x in fake.sent_variables[0]["input"]["quantities"]] == [25, 40]
    assert [x["quantity"] for x in fake.sent_variables[0]["input"]["quantities"]] == [26, 42]


def test_rig_restart_loads_receipt_without_retry(rig):
    prepared, _, make_service, make_receipts = rig
    _send(rig, success_response(prepared))
    fresh_service = make_service()
    saved = make_receipts().load(recovery_repository=fresh_service._recovery,
                                 operation_id=prepared.preview.operation_id)
    assert saved.status is SimulatedResponseStatus.ACKNOWLEDGED_NEEDS_READBACK
    assert fresh_service.decision(operation_id=prepared.preview.operation_id).human_review_required


def test_receipt_write_is_idempotent_without_reexecuting_fake(rig):
    prepared, _, make_service, make_receipts = rig
    result, fake = _send(rig, success_response(prepared))
    copy = make_receipts().record(recovery_repository=make_service()._recovery,
                                  operation_id=prepared.preview.operation_id, assessment=result.assessment)
    assert copy == result.receipt
    assert fake.calls == 1


def test_conflicting_receipt_blocked(rig):
    prepared, _, make_service, make_receipts = rig
    _send(rig, success_response(prepared))
    with pytest.raises(RecoveryConflict, match="conflict"):
        make_receipts().record(recovery_repository=make_service()._recovery,
            operation_id=prepared.preview.operation_id,
            assessment=ResponseAssessment(SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW, "DIFFERENT_RESPONSE"))


def test_receipt_without_dispatch_arm_rejected(rig):
    prepared, _, make_service, make_receipts = rig
    with pytest.raises(RecoveryConflict, match="durable dispatch"):
        make_receipts().record(recovery_repository=make_service()._recovery,
            operation_id=prepared.preview.operation_id,
            assessment=ResponseAssessment(SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW, "TEST_RESPONSE"))


@pytest.mark.parametrize("invalid", [
    ResponseAssessment(SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW, "BAD", automatic_retry_allowed=True),
    ResponseAssessment(SimulatedResponseStatus.ACKNOWLEDGED_NEEDS_READBACK, "BAD", inventory_verified=True),
    ResponseAssessment(SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW, "UPPER CASE"),
    ResponseAssessment(SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW, "X" * 80),
])
def test_fake_receipt_never_claims_safe_replay_or_inventory_verified(rig, invalid):
    prepared, _, make_service, make_receipts = rig
    make_service().arm_dispatch(operation_id=prepared.preview.operation_id,
                                request_digest=prepared.request_digest)
    with pytest.raises(RecoveryConflict):
        make_receipts().record(recovery_repository=make_service()._recovery,
                               operation_id=prepared.preview.operation_id, assessment=invalid)


def test_fake_receipt_immutable_trigger(rig):
    prepared, connect, *_ = rig
    _send(rig, success_response(prepared))
    with connect() as db:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            db.execute("UPDATE supplier_live_batch_fake_receipts SET status='BAD'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute("DELETE FROM supplier_live_batch_fake_receipts")


def test_fake_receipt_checksum_catches_external_tamper(rig):
    prepared, connect, make_service, make_receipts = rig
    _send(rig, success_response(prepared))
    with connect() as db:
        db.execute("DROP TRIGGER trg_supplier_fake_receipts_no_update")
        db.execute("UPDATE supplier_live_batch_fake_receipts SET reason_code='TAMPERED'")
    with pytest.raises(RecoveryConflict, match="integrity"):
        make_receipts().load(recovery_repository=make_service()._recovery,
                             operation_id=prepared.preview.operation_id)


def test_no_shopify_client_initialized(monkeypatch, rig):
    from shopify import client
    def forbidden(*a, **kw):
        raise AssertionError("Shopify client must never be instantiated")
    monkeypatch.setattr(client.ShopifyClient, "__init__", forbidden)
    result, _ = _send(rig, success_response(rig[0]))
    assert result.assessment.status is SimulatedResponseStatus.ACKNOWLEDGED_NEEDS_READBACK


@pytest.fixture
def positive():
    ref = "shopify-automation-lab://v2/operations/11111111-2222-4333-8444-555555555555"
    response = {"data": {"inventorySetQuantities": {
        "userErrors": [],
        "inventoryAdjustmentGroup": {
            "reason": "Inventory correction", "referenceDocumentUri": ref,
            "changes": [{"name": "available", "delta": 3, "quantityAfterChange": None},
                        {"name": "on_hand", "delta": 3, "quantityAfterChange": None}],
        },
    }}}
    return ref, response


def test_policy_accepts_shopify_documentation_null_after_and_extra_state(positive):
    ref, response = positive
    outcome = classify_shopify_response(response, expected_reference_uri=ref)
    assert outcome.status is SimulatedResponseStatus.ACKNOWLEDGED_NEEDS_READBACK
    assert not outcome.inventory_verified


def test_policy_accepts_existing_shopify_client_unwrapped_data(positive):
    ref, response = positive
    outcome = classify_shopify_response(response["data"], expected_reference_uri=ref)
    assert outcome.status is SimulatedResponseStatus.ACKNOWLEDGED_NEEDS_READBACK


@pytest.mark.parametrize("alteration", [
    lambda resp: resp.update({"errors": [{"message": "GraphQL field error"}]}),
    lambda resp: resp.update({"errors": "bad error type"}),
    lambda resp: resp.update({"data": None}),
    lambda resp: resp.update({"inventorySetQuantities": {}}),
    lambda resp: resp["data"].update({"inventorySetQuantities": None}),
    lambda resp: resp["data"]["inventorySetQuantities"].update({"userErrors": None}),
    lambda resp: resp["data"]["inventorySetQuantities"].update({"userErrors": [{}]}),
    lambda resp: resp["data"]["inventorySetQuantities"].update({"inventoryAdjustmentGroup": None}),
    lambda resp: resp["data"]["inventorySetQuantities"]["inventoryAdjustmentGroup"].update({"referenceDocumentUri": "wrong"}),
    lambda resp: resp["data"]["inventorySetQuantities"]["inventoryAdjustmentGroup"].update({"reason": ""}),
    lambda resp: resp["data"]["inventorySetQuantities"]["inventoryAdjustmentGroup"].update({"changes": []}),
    lambda resp: resp["data"]["inventorySetQuantities"]["inventoryAdjustmentGroup"].update({"changes": [{}]}),
    lambda resp: resp["data"]["inventorySetQuantities"]["inventoryAdjustmentGroup"].update({"changes": [{"name": "available", "delta": True, "quantityAfterChange": None}]}),
    lambda resp: resp["data"]["inventorySetQuantities"]["inventoryAdjustmentGroup"].update({"changes": [{"name": "available", "delta": 1, "quantityAfterChange": -1}]}),
    lambda resp: resp["data"]["inventorySetQuantities"]["inventoryAdjustmentGroup"].update({"changes": [{"name": "on_hand", "delta": 1, "quantityAfterChange": None}]}),
    lambda resp: resp["data"]["inventorySetQuantities"].update({"userErrors": [{"code": "ERROR", "message": "problem"}]}),
])
def test_policy_uncertain_on_invalid_or_contradictory_envelopes(positive, alteration):
    ref, response = positive
    alteration(response)
    actual = classify_shopify_response(response, expected_reference_uri=ref)
    assert actual.status is SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW
    assert not actual.automatic_retry_allowed and not actual.inventory_verified


@pytest.mark.parametrize("invalid", [None, False, [], "unexpected", {"status": 200}])
def test_policy_rejects_nondict_responses(positive, invalid):
    ref, _ = positive
    outcome = classify_shopify_response(invalid, expected_reference_uri=ref)
    assert outcome.status is SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW


def test_policy_fails_closed_on_invalid_uri(positive):
    _, response = positive
    result = classify_shopify_response(response, expected_reference_uri="wrong")
    assert result.status is SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW


def test_policy_classifies_valid_shopify_user_error(positive):
    ref, response = positive
    response["data"]["inventorySetQuantities"]["inventoryAdjustmentGroup"] = None
    response["data"]["inventorySetQuantities"]["userErrors"] = [{"code": "STALE_QUANTITY", "message": "Simulated error", "field": ["input"]}]
    actual = classify_shopify_response(response, expected_reference_uri=ref)
    assert actual.status is SimulatedResponseStatus.USER_ERRORS_REQUIRE_REVIEW
    assert not actual.inventory_verified
