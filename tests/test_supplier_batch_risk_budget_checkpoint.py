"""V2.8B/9: exact store/location/targets and limited synthetic proposals."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import replace

import pytest

from scripts.supplier_batch_recovery_synthetic_demo import FakeReadback, build_prepared
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService
from supplier.batch.live_risk_budget import RiskStatus, ControlledTestBudget, assess_test_operation

STORE = "demo-test.myshopify.com"
PAIRS = (("DEMO-1001", "gid://shopify/InventoryItem/1001"),
         ("DEMO-1002", "gid://shopify/InventoryItem/1002"))


@pytest.fixture
def operation(tmp_path):
    path = tmp_path / "isolated.sqlite3"

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
    budget = ControlledTestBudget(STORE, prepared.location_id, PAIRS)
    request = dict(
        archive=ReadOnlyRecoveryArchive(path), operation_id=prepared.preview.operation_id,
        expected_plan_fingerprint=prepared.plan_fingerprint,
        expected_manifest_fingerprint=prepared.manifest_fingerprint,
        observed_store_domain=STORE,
        proposal_source="CONTROLLED_TEST_SYNTHETIC",
        budget=budget,
        readback_port=FakeReadback({"1001": 25, "1002": 40}),
    )
    return request, service, connect


def evaluate(operation, **overrides):
    request = operation[0].copy()
    request.update(overrides)
    return assess_test_operation(**request)


def test_in_scope_is_review_only(operation):
    result = evaluate(operation)
    assert result.status is RiskStatus.REVIEW_OK_FOR_FURTHER_DESIGN
    assert result.successful_inventory_reads == 2 and result.total_abs_delta == 3
    assert result.reviewed_fingerprint and len(result.reviewed_fingerprint) == 64
    assert result.can_continue_to_operator_review
    assert not result.live_execution_allowed and not result.automatic_retry_allowed


@pytest.mark.parametrize("observed_store_domain", [
    "other.myshopify.com", "DEMO-TEST.MYSHOPIFY.COM", "demo-test.myshopify.com.evil.org",
    "https://demo-test.myshopify.com", " demo-test.myshopify.com", "demo-test.myshopify.com/",
    "example.com", "", None, 100, "a\n.myshopify.com",
])
def test_observed_shop_identity_fail_closed(operation, observed_store_domain):
    assert evaluate(operation, observed_store_domain=observed_store_domain).status is RiskStatus.STORE_MISMATCH


@pytest.mark.parametrize("proposal_source", [
    "SUPPLIER_FEED", "MANUAL", "CONTROLLED_TEST", "controlled_test_synthetic", "", None,
])
def test_unattested_sources_blocked(operation, proposal_source):
    assert evaluate(operation, proposal_source=proposal_source).status is RiskStatus.SOURCE_NOT_ALLOWED


@pytest.mark.parametrize("patch", [
    {"store_domain": "fake.com"}, {"store_domain": "demo-test.myshopify.com "},
    {"store_domain": "DEMO-TEST.MYSHOPIFY.COM"}, {"location_id": "gid://shopify/Location/0"},
    {"sku_inventory_items": (("DEMO-1001", "gid://shopify/InventoryItem/1001"),)},
    {"sku_inventory_items": (("DEMO-1001", "gid://shopify/InventoryItem/1001"),
                             ("DEMO-1001", "gid://shopify/InventoryItem/1002"))},
    {"sku_inventory_items": (("DEMO-1001", "gid://shopify/InventoryItem/1001"),
                             ("DEMO-1002", "gid://shopify/InventoryItem/1001"))},
    {"max_delta_per_item": 0}, {"max_delta_per_item": 3}, {"max_delta_per_item": True},
    {"max_total_delta": 0}, {"max_total_delta": 4}, {"max_total_delta": 2.0},
    {"max_target_quantity": 0}, {"max_target_quantity": 1001}, {"max_target_quantity": True},
])
def test_invalid_policy_rejected(operation, patch):
    bad = replace(operation[0]["budget"], **patch)
    assert evaluate(operation, budget=bad).status is RiskStatus.INVALID_POLICY


def test_wrong_location_blocks(operation):
    bad = replace(operation[0]["budget"], location_id="gid://shopify/Location/999002")
    assert evaluate(operation, budget=bad).status is RiskStatus.REVIEW_BLOCKED


@pytest.mark.parametrize("sku_inventory_items", [
    (("DEMO-1001", "gid://shopify/InventoryItem/1001"), ("DEMO-9999", "gid://shopify/InventoryItem/1002")),
    (("DEMO-1001", "gid://shopify/InventoryItem/1002"), ("DEMO-1002", "gid://shopify/InventoryItem/1001")),
])
def test_target_allowlist_detects_wrong_mapping(operation, sku_inventory_items):
    bad = replace(operation[0]["budget"], sku_inventory_items=sku_inventory_items)
    assert evaluate(operation, budget=bad).status is RiskStatus.TARGET_MISMATCH


@pytest.mark.parametrize("patch", [
    {"max_delta_per_item": 1}, {"max_total_delta": 2}, {"max_target_quantity": 41},
])
def test_conservative_budget_rejects(operation, patch):
    bad = replace(operation[0]["budget"], **patch)
    assert evaluate(operation, budget=bad).status is RiskStatus.RISK_BUDGET_EXCEEDED


def test_review_detects_inventory_drift(operation):
    bad = FakeReadback({"1001": 25, "1002": 39})
    assert evaluate(operation, readback_port=bad).status is RiskStatus.REVIEW_BLOCKED


def test_plan_identity_mismatch(operation):
    assert evaluate(operation, expected_plan_fingerprint="f"*64).status is RiskStatus.REVIEW_BLOCKED


def test_bad_fingerprint_shape(operation):
    assert evaluate(operation, expected_manifest_fingerprint="nope").status is RiskStatus.IDENTITY_MISMATCH


def test_prior_dispatch_fails_closed(operation):
    data, service, _ = operation
    service.arm_dispatch(operation_id=data["operation_id"], request_digest=service._recovery.load_snapshot(data["operation_id"]).request_digest)
    assert evaluate(operation).status is RiskStatus.PREVIOUS_DISPATCH


def test_tampered_snapshot_rejected(operation):
    _, _, connect = operation
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with connect() as db:
            db.execute("UPDATE supplier_live_batch_request_snapshots SET payload_sha256=?", ("0"*64,))
    assert evaluate(operation).status is RiskStatus.REVIEW_OK_FOR_FURTHER_DESIGN


def test_readback_failure_is_not_success(operation):
    class Broken:
        def read_available(self, **kwargs):
            raise ConnectionError("fake offline failure")
    assert evaluate(operation, readback_port=Broken()).status is RiskStatus.REVIEW_BLOCKED


def test_no_network_write_methods_exist():
    assert not hasattr(ControlledTestBudget, "execute")
    assert not hasattr(RiskStatus, "send")
