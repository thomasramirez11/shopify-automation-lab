"""V2.8B/8: full composed fake-only operator review -> journal -> fake send."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from scripts.supplier_batch_fake_sender_checkpoint_demo import acknowledged, rejected
from scripts.supplier_batch_recovery_synthetic_demo import FakeReadback, build_prepared
from supplier.batch.live_fake_receipt_repository import SupplierLiveBatchFakeReceiptRepository
from supplier.batch.live_fake_sender import ScriptedFakeShopifyTransport, SupplierLiveBatchFakeSender
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository
from supplier.batch.live_operator_review import OperatorReviewStatus, review_saved_batch
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive
from supplier.batch.live_recovery_models import RecoveryConflict, RecoveryState
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService
from supplier.batch.live_sender_rehearsal import RehearsalStatus, SupplierBatchSenderRehearsal


@pytest.fixture
def rig(tmp_path):
    path = tmp_path / "rehearsal.sqlite3"

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

    prepared = build_prepared()
    service = SupplierLiveBatchRecoveryService(
        intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connect),
        recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connect),
    )
    service.prepare(prepared)
    archive = ReadOnlyRecoveryArchive(path)
    sender = SupplierLiveBatchFakeSender(
        recovery_service=service,
        receipt_repository=SupplierLiveBatchFakeReceiptRepository(connection_factory=connect),
    )
    runner = SupplierBatchSenderRehearsal(archive=archive, fake_sender=sender)
    args = dict(operation_id=prepared.preview.operation_id,
                expected_plan_fingerprint=prepared.plan_fingerprint,
                expected_manifest_fingerprint=prepared.manifest_fingerprint,
                expected_location_id=prepared.location_id)
    def fingerprint():
        ready = review_saved_batch(archive=archive, readback_port=FakeReadback({"1001": 25, "1002": 40}), **args)
        assert ready.status == OperatorReviewStatus.REVIEW_READY
        return ready.review_fingerprint
    return prepared, service, archive, runner, args, fingerprint, connect


_DEFAULT_RESPONSE = object()


def send(rig, response=_DEFAULT_RESPONSE, *, quantities=None, fingerprint=None, **override):
    prepared, service, archive, runner, args, make_fp, connect = rig
    fake = ScriptedFakeShopifyTransport(acknowledged(prepared) if response is _DEFAULT_RESPONSE else response)
    report = runner.run_once(
        **(args | override),
        expected_review_fingerprint=fingerprint if fingerprint is not None else make_fp(),
        readback_port=FakeReadback({"1001": 25, "1002": 40} if quantities is None else quantities),
        transport=fake,
    )
    return report, fake


def events(rig):
    prepared, service, *_ = rig
    return service._recovery.events(prepared.preview.operation_id)


def test_ack_path_arms_once_then_fake_ack(rig):
    result, fake = send(rig)
    assert result.status is RehearsalStatus.FAKE_ACK_NEEDS_READBACK
    assert result.review_status is OperatorReviewStatus.REVIEW_READY
    assert result.recovery_state is RecoveryState.ARMED_OUTCOME_UNCERTAIN
    assert result.journal_event_count == 1
    assert result.fake_send_calls == fake.calls == 1
    assert result.review_fingerprint is not None
    assert not result.inventory_verified_by_mutation
    assert not result.live_execution_allowed and not result.automatic_retry_allowed


def test_ack_response_preserves_idempotency_key_and_cas(rig):
    prepared = rig[0]
    result, fake = send(rig)
    assert fake.sent_queries == [prepared.preview.query]
    assert fake.sent_variables == [prepared.preview.variables]
    assert fake.sent_variables[0]["idempotencyKey"] == prepared.preview.operation_id
    assert [(t["changeFromQuantity"], t["quantity"]) for t in fake.sent_variables[0]["input"]["quantities"]] == [(25,26),(40,42)]


@pytest.mark.parametrize("reply,status", [
    ("user_errors", RehearsalStatus.FAKE_USER_ERRORS),
    (TimeoutError("hidden"), RehearsalStatus.FAKE_UNKNOWN),
    (ConnectionError("hidden"), RehearsalStatus.FAKE_UNKNOWN),
    ({"errors": [{"message": "bad"}]}, RehearsalStatus.FAKE_UNKNOWN),
    ({"data": {}}, RehearsalStatus.FAKE_UNKNOWN),
    (None, RehearsalStatus.FAKE_UNKNOWN),
])
def test_responses_remain_fail_closed(rig, reply, status):
    result, fake = send(rig, rejected(rig[0]) if reply == "user_errors" else reply)
    assert result.status is status
    assert fake.calls == 1
    assert not result.automatic_retry_allowed
    assert len(events(rig)) >= 1


@pytest.mark.parametrize("quantities", [
    {"1001": 24, "1002": 40},
    {"1001": 25, "1002": 41},
    {"1001": 26, "1002": 42},
    {"1001": 25},
    {"1001": 0, "1002": 40},
])
def test_drift_or_untrustworthy_readback_never_sends(rig, quantities):
    result, fake = send(rig, quantities=quantities)
    assert result.status is RehearsalStatus.REVIEW_BLOCKED
    assert fake.calls == 0
    assert not events(rig)


@pytest.mark.parametrize("key,bad", [
    ("expected_plan_fingerprint", "a"*64),
    ("expected_manifest_fingerprint", "b"*64),
    ("expected_location_id", "gid://shopify/Location/222222"),
    ("operation_id", "invalid"),
])
def test_wrong_identity_no_send(rig, key, bad):
    result, fake = send(rig, **{key: bad})
    assert result.status is RehearsalStatus.REVIEW_BLOCKED
    assert fake.calls == 0
    assert not events(rig)


@pytest.mark.parametrize("value", ["f"*64, "1"*64, None, "bad", "A"*64, 42, True])
def test_bad_review_evidence_blocks_before_fake_dispatch(rig, value):
    prepared, _, _, runner, args, make_fp, _ = rig
    fake = ScriptedFakeShopifyTransport(acknowledged(prepared))
    result = runner.run_once(**args, expected_review_fingerprint=value,
                             readback_port=FakeReadback({"1001":25,"1002":40}), transport=fake)
    assert result.status in (RehearsalStatus.INPUT_REJECTED, RehearsalStatus.REVIEW_FINGERPRINT_MISMATCH)
    assert fake.calls == 0
    assert not events(rig)


def test_previous_send_blocks_fresh_review_without_second_send(rig):
    first, fake = send(rig)
    assert fake.calls == 1
    prepared, service, archive, runner, args, _, _ = rig
    second_transport = ScriptedFakeShopifyTransport(acknowledged(prepared))
    second = runner.run_once(**args, expected_review_fingerprint=first.review_fingerprint,
        readback_port=FakeReadback({"1001": 26,"1002":42}), transport=second_transport)
    assert second.status is RehearsalStatus.REVIEW_BLOCKED
    assert second.review_status is OperatorReviewStatus.DISPATCH_HISTORY
    assert second_transport.calls == 0
    assert len(events(rig)) == 1


def test_armed_after_review_during_inventory_reads_blocks(rig):
    prepared, service, archive, runner, args, make_fp, _ = rig
    class ConcurrentPort:
        def __init__(self):
            self.n = 0
            self.other = FakeReadback({"1001":25,"1002":40})
        def read_available(self, *, inventory_item_id, location_id):
            self.n += 1
            if self.n == 1:
                service.arm_dispatch(operation_id=prepared.preview.operation_id,
                                     request_digest=prepared.request_digest)
            return self.other.read_available(inventory_item_id=inventory_item_id, location_id=location_id)
    fake = ScriptedFakeShopifyTransport(acknowledged(prepared))
    result = runner.run_once(**args, expected_review_fingerprint=make_fp(),
        readback_port=ConcurrentPort(), transport=fake)
    assert result.status is RehearsalStatus.REVIEW_BLOCKED
    assert result.review_status is OperatorReviewStatus.RECORD_CHANGED_DURING_REVIEW
    assert fake.calls == 0 and len(events(rig)) == 1


def test_fake_readback_observes_targets_but_no_authorized_retry(rig):
    prepared, service, archive, runner, args, make_fp, _ = rig
    fake = ScriptedFakeShopifyTransport(acknowledged(prepared))
    result = runner.run_once(**args, expected_review_fingerprint=make_fp(),
        readback_port=FakeReadback({"1001":25,"1002":40}), transport=fake,
        post_send_readback_port=FakeReadback({"1001":26,"1002":42}))
    assert result.recovery_state is RecoveryState.READBACK_TARGET_OBSERVED
    assert result.journal_event_count == 2
    assert not result.automatic_retry_allowed and not result.live_execution_allowed
    assert result.inventory_verified_by_mutation is False
    assert service.decision(operation_id=prepared.preview.operation_id).human_review_required


def test_fake_readback_baselines_cannot_enable_retry(rig):
    prepared, service, archive, runner, args, make_fp, _ = rig
    fake = ScriptedFakeShopifyTransport(acknowledged(prepared))
    result = runner.run_once(**args, expected_review_fingerprint=make_fp(),
        readback_port=FakeReadback({"1001":25,"1002":40}), transport=fake,
        post_send_readback_port=FakeReadback({"1001":25,"1002":40}))
    assert result.recovery_state is RecoveryState.READBACK_BASELINE_OBSERVED
    assert not result.automatic_retry_allowed


def test_fake_readback_fail_does_not_suggest_retry(rig):
    prepared, service, archive, runner, args, make_fp, _ = rig
    fake = ScriptedFakeShopifyTransport(acknowledged(prepared))
    result = runner.run_once(**args, expected_review_fingerprint=make_fp(),
        readback_port=FakeReadback({"1001":25,"1002":40}), transport=fake,
        post_send_readback_port=FakeReadback({"1001":25}))
    assert result.recovery_state is RecoveryState.READBACK_FAILED
    assert not result.automatic_retry_allowed


def test_untrusted_non_fake_port_rejected_before_arm(rig):
    prepared, service, archive, runner, args, make_fp, _ = rig
    class RealClientLike:
        def send(self, query, variables):
            raise AssertionError("network request must NEVER be invoked")
    with pytest.raises(RecoveryConflict, match="ONLY"):
        runner.run_once(**args, expected_review_fingerprint=make_fp(),
                        readback_port=FakeReadback({"1001":25,"1002":40}), transport=RealClientLike())
    assert not events(rig)


def test_fake_subclass_rejected(rig):
    prepared, service, archive, runner, args, make_fp, _ = rig
    class Subclass(ScriptedFakeShopifyTransport):
        pass
    with pytest.raises(RecoveryConflict, match="ONLY"):
        runner.run_once(**args, expected_review_fingerprint=make_fp(),
                        readback_port=FakeReadback({"1001":25,"1002":40}), transport=Subclass(acknowledged(prepared)))
    assert not events(rig)


def test_post_readback_invalid_port_blocks_early(rig):
    prepared, service, archive, runner, args, make_fp, _ = rig
    fake = ScriptedFakeShopifyTransport(acknowledged(prepared))
    result = runner.run_once(**args, expected_review_fingerprint=make_fp(),
                            readback_port=FakeReadback({"1001":25,"1002":40}),
                            post_send_readback_port=object(), transport=fake)
    assert result.status is RehearsalStatus.INPUT_REJECTED
    assert fake.calls == 0 and not events(rig)


def test_prior_arm_after_operator_review_before_send_blocks(rig, monkeypatch):
    prepared, service, archive, runner, args, make_fp, _ = rig
    original = runner._sender.send_once
    def arm_then_send(*, operation_id, transport):
        service.arm_dispatch(operation_id=operation_id, request_digest=prepared.request_digest)
        return original(operation_id=operation_id, transport=transport)
    monkeypatch.setattr(runner._sender, "send_once", arm_then_send)
    fake = ScriptedFakeShopifyTransport(acknowledged(prepared))
    result = runner.run_once(**args, expected_review_fingerprint=make_fp(),
                            readback_port=FakeReadback({"1001":25,"1002":40}), transport=fake)
    assert result.status is RehearsalStatus.SEND_ALREADY_ARMED
    assert fake.calls == 0
    assert len(events(rig)) == 1


def test_disk_failure_receipt_persistence_never_reports_success(rig):
    prepared, service, archive, runner, args, make_fp, connect = rig
    with connect() as db:
        runner._sender._receipt_repository._initialize(db)
        db.executescript("""CREATE TRIGGER fail_receipt BEFORE INSERT ON supplier_live_batch_fake_receipts
            BEGIN SELECT RAISE(ABORT, 'disk issue'); END;""")
    fake = ScriptedFakeShopifyTransport(acknowledged(prepared))
    with pytest.raises(sqlite3.IntegrityError):
        runner.run_once(**args, expected_review_fingerprint=make_fp(),
            readback_port=FakeReadback({"1001":25,"1002":40}), transport=fake)
    assert fake.calls == 1 and len(events(rig)) == 1


def test_no_send_transport_exception_keyboard_interrupt_is_uncertain(rig):
    prepared, service, archive, runner, args, make_fp, connect = rig
    fake = ScriptedFakeShopifyTransport(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        runner.run_once(**args, expected_review_fingerprint=make_fp(),
            readback_port=FakeReadback({"1001":25,"1002":40}), transport=fake)
    assert fake.calls == 1 and len(events(rig)) == 1
    assert service.decision(operation_id=prepared.preview.operation_id).automatic_retry_allowed is False


def test_constructor_rejects_fake_classes(rig):
    prepared, service, archive, runner, args, make_fp, connect = rig
    with pytest.raises(RecoveryConflict):
        SupplierBatchSenderRehearsal(archive=object(), fake_sender=runner._sender)
    with pytest.raises(RecoveryConflict):
        SupplierBatchSenderRehearsal(archive=archive, fake_sender=object())


def test_archive_does_not_update_audit_when_only_reviewing(rig):
    prepared, service, archive, runner, args, make_fp, connect = rig
    before = rig[6]  # factory; underlying data checked via journal instead
    fake = ScriptedFakeShopifyTransport(acknowledged(prepared))
    result = runner.run_once(**args, expected_review_fingerprint="e"*64,
        readback_port=FakeReadback({"1001":25,"1002":40}), transport=fake)
    assert result.status is RehearsalStatus.REVIEW_FINGERPRINT_MISMATCH
    assert fake.calls == 0 and not events(rig)


def test_offline_module_has_no_real_live_sender_entrypoint():
    import supplier.batch.live_sender_rehearsal as mod
    assert "FAKE-ONLY" in mod.__doc__
    assert not hasattr(mod, "send_live_shopify")
