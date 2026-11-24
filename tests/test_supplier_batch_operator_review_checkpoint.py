"""V2.8B/7 offline operator review — real source, no live networking."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import replace

import pytest

from scripts.supplier_batch_recovery_synthetic_demo import FakeReadback, build_prepared
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository
from supplier.batch.live_operator_review import OperatorReviewStatus as Status, review_saved_batch
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService
from supplier.execution.readback import InventoryReadbackState


@pytest.fixture
def scenario(tmp_path):
    prepared = build_prepared()
    path = tmp_path / "recovery.sqlite3"

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

    service = SupplierLiveBatchRecoveryService(
        intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connect),
        recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connect),
    )
    service.prepare(prepared)
    archive = ReadOnlyRecoveryArchive(path)
    args = dict(archive=archive, operation_id=prepared.preview.operation_id,
                expected_plan_fingerprint=prepared.plan_fingerprint,
                expected_manifest_fingerprint=prepared.manifest_fingerprint,
                expected_location_id=prepared.location_id)
    return args, service, path, prepared


def call(scenario, quantities=None, **overrides):
    args, _, _, _ = scenario
    return review_saved_batch(**(args | overrides), readback_port=FakeReadback(quantities or {"1001": 25, "1002": 40}))


def test_baseline_review_passes_without_permission(scenario):
    report = call(scenario)
    assert report.status is Status.REVIEW_READY
    assert report.reason_code == "TWO_READS_MATCH_SAVED_CAS_BASELINES"
    assert report.read_count == 2
    assert len(report.review_fingerprint) == 64
    assert report.verified_items == (("DEMO-1001", 25, 25, 26), ("DEMO-1002", 40, 40, 42))
    assert report.can_continue_to_operator_review
    assert not report.live_execution_allowed and not report.automatic_retry_allowed
    assert report.human_review_required


def test_review_is_deterministic_and_does_not_write_db(scenario):
    args, _, path, _ = scenario
    before = path.read_bytes()
    a = call(scenario)
    b = call(scenario)
    assert a == b
    assert path.read_bytes() == before
    _, events = args["archive"].load_verified(args["operation_id"])
    assert events == ()


@pytest.mark.parametrize("values", [
    {"1001": 25, "1002": 39}, {"1001": 24, "1002": 40},
    {"1001": 26, "1002": 40}, {"1001": 25, "1002": 42},
    {"1001": 26, "1002": 42}, {"1001": 0, "1002": 0},
    {"1001": 2000, "1002": 3000},
])
def test_any_inventory_drift_blocks(scenario, values):
    r = call(scenario, values)
    assert r.status is Status.INVENTORY_STALE
    assert r.read_count == 2
    assert not r.can_continue_to_operator_review
    assert r.review_fingerprint is None
    assert not r.live_execution_allowed


@pytest.mark.parametrize("field,bad", [
    ("expected_plan_fingerprint", "f" * 64),
    ("expected_manifest_fingerprint", "e" * 64),
    ("expected_location_id", "gid://shopify/Location/101010"),
])
def test_wrong_expected_identity_rejects_before_reads(scenario, field, bad):
    r = call(scenario, **{field: bad})
    assert r.status is Status.IDENTITY_MISMATCH
    assert r.read_count == 0


@pytest.mark.parametrize("field,bad", [
    ("expected_plan_fingerprint", "1"),
    ("expected_plan_fingerprint", None),
    ("expected_manifest_fingerprint", "G" * 64),
    ("expected_manifest_fingerprint", 123),
    ("expected_location_id", "shopify/Location/1"),
    ("expected_location_id", "gid://shopify/Location/0"),
    ("operation_id", None),
])
def test_invalid_operator_input_fails_closed(scenario, field, bad):
    r = call(scenario, **{field: bad})
    assert r.status is Status.POLICY_REJECTED
    assert not r.can_continue_to_operator_review


def test_armed_operation_blocks_before_fresh_read(scenario):
    args, service, _, prepared = scenario
    service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    class NoReads:
        def read_available(self, **kw):
            raise AssertionError("armed operation must never be put through new-send review")
    report = review_saved_batch(**args, readback_port=NoReads())
    assert report.status is Status.DISPATCH_HISTORY
    assert report.read_count == 0
    assert not report.live_execution_allowed


def test_armed_after_outcome_unknown_blocks(scenario):
    args, service, _, prepared = scenario
    service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
    service.note_outcome_unknown(operation_id=prepared.preview.operation_id)
    assert call(scenario).status is Status.DISPATCH_HISTORY


def test_injected_readback_failure_blocks(scenario):
    assert call(scenario, {"1001": 25}).status is Status.INSPECTION_BLOCKED


def test_missing_operation_denied(scenario):
    report = call(scenario, operation_id="cbed04af-6ec2-4379-b4a8-cd1234567890")
    assert report.status is Status.ARCHIVE_UNTRUSTED


def test_wrong_archive_class_denied(scenario):
    assert call(scenario, archive=object()).status is Status.ARCHIVE_UNTRUSTED


def test_readback_flag_forgery_denied(scenario):
    class FakeFlags:
        def read_available(self, *, inventory_item_id, location_id):
            return InventoryReadbackState(
                inventory_item_id=inventory_item_id,
                sku="DEMO-" + inventory_item_id.rsplit("/", 1)[-1],
                location_id=location_id, location_name="Mock",
                tracked="true", location_active=True, level_active=True,
                available_quantity=25,
            )
    args, _, _, _ = scenario
    result = review_saved_batch(**args, readback_port=FakeFlags())
    assert result.status is Status.INSPECTION_BLOCKED


def test_missing_port_is_policy_rejection(scenario):
    args, _, _, _ = scenario
    assert review_saved_batch(**args, readback_port=None).status is Status.POLICY_REJECTED


def test_concurrent_arm_while_reading_blocks(scenario):
    args, service, _, prepared = scenario
    class Concurrent:
        def __init__(self):
            self.n = 0
            self.port = FakeReadback({"1001": 25, "1002": 40})
        def read_available(self, *, inventory_item_id, location_id):
            self.n += 1
            if self.n == 1:
                service.arm_dispatch(operation_id=prepared.preview.operation_id, request_digest=prepared.request_digest)
            return self.port.read_available(inventory_item_id=inventory_item_id, location_id=location_id)
    result = review_saved_batch(**args, readback_port=Concurrent())
    assert result.status is Status.RECORD_CHANGED_DURING_REVIEW
    assert result.read_count == 2
    assert not result.can_continue_to_operator_review


def test_isolated_source_no_send_function():
    import supplier.batch.live_operator_review as module
    text = module.__doc__
    assert "no dispatch authorization" in text
    assert not hasattr(module, "send_live_batch")
