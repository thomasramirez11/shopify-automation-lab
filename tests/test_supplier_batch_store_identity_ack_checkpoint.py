"""V2.8B/10: authenticated shop-domain pinning + review-only acknowledgement."""
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
from supplier.batch.live_review_acknowledgement import (
    ReviewAckStatus, review_with_authenticated_identity,
)
from supplier.batch.live_risk_budget import ControlledTestBudget
from supplier.batch.live_store_identity import (
    SHOP_IDENTITY_QUERY, ShopifyStoreIdentityReadOnly, StoreIdentityRejected,
)

SHOP = "demo-test.myshopify.com"
GID = "gid://shopify/Shop/1234"


class FakeShop:
    store_domain = SHOP

    _UNSET = object()

    def __init__(self, *, response=_UNSET, error=None, host=SHOP):
        self.store_domain = host
        self.response = response if response is not self._UNSET else {"shop": {
            "id": GID, "myshopifyDomain": SHOP,
        }}
        self.error = error
        self.calls = []

    def graphql(self, query, variables=None):
        self.calls.append((query, variables))
        assert query == SHOP_IDENTITY_QUERY and variables == {}
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def ready(tmp_path):
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
    fake = FakeShop()
    budget = ControlledTestBudget(
        store_domain=SHOP, location_id=prepared.location_id,
        sku_inventory_items=(("DEMO-1001", "gid://shopify/InventoryItem/1001"),
                             ("DEMO-1002", "gid://shopify/InventoryItem/1002")),
    )
    return dict(
        shop_identity=ShopifyStoreIdentityReadOnly(fake), expected_shop_id=GID,
        archive=ReadOnlyRecoveryArchive(path), operation_id=prepared.preview.operation_id,
        expected_plan_fingerprint=prepared.plan_fingerprint,
        expected_manifest_fingerprint=prepared.manifest_fingerprint,
        proposal_source="CONTROLLED_TEST_SYNTHETIC", budget=budget,
        readback_port=FakeReadback({"1001": 25, "1002": 40}),
    ), fake, service


def review(ready, **changes):
    req = dict(ready[0])
    req.update(changes)
    return review_with_authenticated_identity(**req)


def test_shop_identity_accepts_matching_authenticated_domain():
    fake = FakeShop()
    adapter = ShopifyStoreIdentityReadOnly(fake)
    result = adapter.read()
    assert result.shop_id == GID and result.domain == SHOP
    assert fake.calls == [(SHOP_IDENTITY_QUERY, {})]
    assert adapter.read_queries == 1


@pytest.mark.parametrize("host", ["", "EXAMPLE.myshopify.com", "a.myshopify.com.evil.net",
                                  "https://demo-test.myshopify.com", "demo-test.myshopify.com/",
                                  "example.com", 42, None, "foo\n.myshopify.com"])
def test_client_host_is_strict(host):
    with pytest.raises(StoreIdentityRejected):
        ShopifyStoreIdentityReadOnly(FakeShop(host=host))


@pytest.mark.parametrize("bad", [
    None, [], 4, {}, {"shop": None}, {"shop": {}}, {"shop": []},
    {"shop": {"id": GID, "myshopifyDomain": SHOP, "something": "else"}},
    {"shop": {"id": GID}}, {"shop": {"id": GID, "myshopifyDomain": "other.myshopify.com"}},
    {"shop": {"id": GID, "myshopifyDomain": SHOP.upper()}},
    {"shop": {"id": "gid://shopify/Product/10", "myshopifyDomain": SHOP}},
    {"shop": {"id": "gid://shopify/Shop/0", "myshopifyDomain": SHOP}},
    {"shop": {"id": "gid://shopify/Shop/abc", "myshopifyDomain": SHOP}},
    {"shop": {"id": 4, "myshopifyDomain": SHOP}},
])
def test_malformed_identity_response_fails_closed(bad):
    reader = ShopifyStoreIdentityReadOnly(FakeShop(response=bad))
    with pytest.raises(StoreIdentityRejected):
        reader.read()


def test_network_exception_is_sanitized():
    adapter = ShopifyStoreIdentityReadOnly(FakeShop(error=RuntimeError("sensitive TOKEN abc")))
    with pytest.raises(StoreIdentityRejected, match="authenticated shop identity unavailable") as e:
        adapter.read()
    assert "TOKEN" not in str(e.value)


def test_review_returns_bound_challenge_and_no_execution(ready):
    result = review(ready)
    assert result.status is ReviewAckStatus.ACKNOWLEDGEMENT_REQUIRED
    assert result.expected_acknowledgement.startswith("ACK-REVIEW-")
    assert len(result.expected_acknowledgement) == len("ACK-REVIEW-") + 24
    assert result.successful_inventory_reads == 2
    assert not result.operator_authenticated
    assert not result.live_execution_allowed and not result.automatic_retry_allowed


def test_correct_acknowledgement_requires_fresh_identity_and_inventory(ready):
    expected = review(ready).expected_acknowledgement
    fake = ready[1]
    initial_calls = len(fake.calls)
    result = review(ready, operator_acknowledgement=expected)
    assert result.status is ReviewAckStatus.ACKNOWLEDGED_FOR_FURTHER_REVIEW
    assert result.can_continue_to_operator_review
    assert len(fake.calls) == initial_calls + 1
    assert not result.live_execution_allowed and not result.operator_authenticated


@pytest.mark.parametrize("ack", ["", "no", "ACK-REVIEW-", " ACK-REVIEW-", 123, True])
def test_wrong_acknowledgement_blocks(ready, ack):
    assert review(ready, operator_acknowledgement=ack).status is ReviewAckStatus.ACKNOWLEDGEMENT_MISMATCH


@pytest.mark.parametrize("wrong", ["gid://shopify/Shop/999", "gid://shopify/Shop/0", "1234", None])
def test_wrong_expected_shop_id_blocks_before_risk(ready, wrong):
    out = review(ready, expected_shop_id=wrong)
    assert out.status is ReviewAckStatus.SHOP_ID_MISMATCH
    assert out.successful_inventory_reads == 0


def test_auth_shop_id_mismatch_blocks(ready):
    fake = ready[1]
    fake.response = {"shop": {"id": "gid://shopify/Shop/9999", "myshopifyDomain": SHOP}}
    assert review(ready).status is ReviewAckStatus.SHOP_ID_MISMATCH


def test_shop_domain_mismatch_policy_blocks(ready):
    altered = replace(ready[0]["budget"], store_domain="wrong.myshopify.com")
    assert review(ready, budget=altered).status is ReviewAckStatus.STORE_MISMATCH


def test_query_failure_blocks_before_inventory(ready):
    ready[1].error = ConnectionError("secret token")
    result = review(ready)
    assert result.status is ReviewAckStatus.IDENTITY_UNAVAILABLE
    assert result.successful_inventory_reads == 0


def test_fake_identity_object_not_accepted(ready):
    assert review(ready, shop_identity=object()).status is ReviewAckStatus.IDENTITY_UNAVAILABLE


def test_inventory_drift_invalidates_ack(ready):
    ack = review(ready).expected_acknowledgement
    drift = FakeReadback({"1001": 25, "1002": 39})
    assert review(ready, readback_port=drift, operator_acknowledgement=ack).status is ReviewAckStatus.REVIEW_BLOCKED


def test_budget_change_invalidates_ack(ready):
    ack = review(ready).expected_acknowledgement
    altered = replace(ready[0]["budget"], max_target_quantity=500)
    assert review(ready, budget=altered, operator_acknowledgement=ack).status is ReviewAckStatus.ACKNOWLEDGEMENT_MISMATCH


def test_plan_fingerprint_change_blocks_ack(ready):
    ack = review(ready).expected_acknowledgement
    assert review(ready, expected_plan_fingerprint="f"*64,
                  operator_acknowledgement=ack).status is ReviewAckStatus.REVIEW_BLOCKED


def test_dispatch_armed_blocks_ack(ready):
    ack = review(ready).expected_acknowledgement
    service = ready[2]
    opid = ready[0]["operation_id"]
    snapshot = service._recovery.load_snapshot(opid)
    service.arm_dispatch(operation_id=opid, request_digest=snapshot.request_digest)
    assert review(ready, operator_acknowledgement=ack).status is ReviewAckStatus.REVIEW_BLOCKED


def test_untrusted_source_blocks(ready):
    assert review(ready, proposal_source="SUPPLIER_FEED").status is ReviewAckStatus.REVIEW_BLOCKED


def test_no_sender_methods_exposed():
    assert not hasattr(ShopifyStoreIdentityReadOnly, "set_inventory")
    assert not hasattr(ShopifyStoreIdentityReadOnly, "execute")
    assert not hasattr(type(review_with_authenticated_identity), "set_inventory")


def test_cli_live_readonly_uses_one_shop_query(monkeypatch, capsys):
    from scripts import supplier_shop_identity_readonly as cli
    from scripts import supplier_live_batch_preflight as previous
    fake = FakeShop()
    monkeypatch.setattr(previous, "build_client", lambda: fake)
    assert cli.main([]) == 0
    assert fake.calls == [(SHOP_IDENTITY_QUERY, {})]
    output = capsys.readouterr().out
    assert "IDENTITY STATUS: VERIFIED" in output
    assert "LIVE SHOPIFY WRITES: 0" in output


def test_cli_pin_shop_matches(monkeypatch, capsys):
    from scripts import supplier_shop_identity_readonly as cli
    from scripts import supplier_live_batch_preflight as previous
    fake = FakeShop()
    monkeypatch.setattr(previous, "build_client", lambda: fake)
    assert cli.main(["--expected-shop-id", GID]) == 0
    assert "PINNED SHOP ID MATCH" in capsys.readouterr().out


def test_cli_pin_mismatch_blocks(monkeypatch, capsys):
    from scripts import supplier_shop_identity_readonly as cli
    from scripts import supplier_live_batch_preflight as previous
    fake = FakeShop()
    monkeypatch.setattr(previous, "build_client", lambda: fake)
    assert cli.main(["--expected-shop-id", "gid://shopify/Shop/4567"]) == 2
    assert "SHOP ID MISMATCH" in capsys.readouterr().out
    assert fake.calls == [(SHOP_IDENTITY_QUERY, {})]


def test_cli_auth_failure_sanitized(monkeypatch, capsys):
    from scripts import supplier_shop_identity_readonly as cli
    from scripts import supplier_live_batch_preflight as previous
    monkeypatch.setattr(previous, "build_client", lambda: FakeShop(error=RuntimeError("token secret")))
    assert cli.main([]) == 2
    output = capsys.readouterr().out
    assert "token secret" not in output and "BLOCKED" in output


def test_cli_invalid_gid_rejected_before_network(monkeypatch):
    from scripts import supplier_shop_identity_readonly as cli
    from scripts import supplier_live_batch_preflight as previous
    called = []
    monkeypatch.setattr(previous, "build_client", lambda: called.append(1))
    with pytest.raises(SystemExit) as e:
        cli.main(["--expected-shop-id", "not-a-gid"])
    assert e.value.code == 2
    assert not called
