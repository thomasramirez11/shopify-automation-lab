"""V2.8B/11: integrated authenticated shop + inventory READ-ONLY review."""
from __future__ import annotations

import re
from dataclasses import replace

import pytest

from supplier.batch.approval import evaluate_batch_approval
from supplier.batch.builder import build_batch_safety_manifest
from supplier.batch.live_pinned_readonly_controller import (
    PinnedReadOnlySession, PinnedReadOnlyStatus, inspect_pinned_live_candidate,
)
from supplier.batch.live_readonly_query_fence import ReadOnlyQueryRejected
from supplier.batch.live_store_identity import SHOP_IDENTITY_QUERY, StoreIdentityRejected
from supplier.batch.live_request_contract import INVENTORY_SET_QUANTITIES
from supplier.batch.models import BatchSafetyPolicy
from supplier.decision.models import SupplierSyncDecision, SyncDecisionReason, SyncDecisionStatus
from supplier.execution.readback import INVENTORY_READBACK_QUERY
from supplier.execution.shopify_adapter import ShopifyInventoryTarget
from supplier.plan.builder import build_dry_run_sync_plan

SHOP = "integration-test.myshopify.com"
GID = "gid://shopify/Shop/12345"
WRONG_GID = "gid://shopify/Shop/99999"
LOCATION = "gid://shopify/Location/9001"
BASELINES = {"1001": 25, "1002": 40}


class ShopAndInventoryFake:
    store_domain = SHOP

    def __init__(self, *, shop_ids=(GID, GID), shop_domains=(SHOP, SHOP),
                 inventories=None, fail_at=None, bad_field=None):
        self.shop_ids = shop_ids
        self.shop_domains = shop_domains
        self.inventories = inventories or {
            "1001": (25, 25), "1002": (40, 40),
        }
        self.fail_at = fail_at
        self.bad_field = bad_field
        self.calls = []
        self.identities = 0
        self.per_item_reads = {"1001": 0, "1002": 0}

    def graphql(self, query, variables):
        self.calls.append((query, variables))
        if self.fail_at == len(self.calls):
            raise TimeoutError("SENSITIVE_AUTH_TOKEN")
        if query == SHOP_IDENTITY_QUERY:
            index = self.identities
            self.identities += 1
            return {"shop": {"id": self.shop_ids[index],
                             "myshopifyDomain": self.shop_domains[index]}}
        assert query == INVENTORY_READBACK_QUERY, "unexpected network query"
        item_id = variables["inventoryItemId"]
        location_id = variables["locationId"]
        suffix = item_id.rsplit("/", 1)[-1]
        index = self.per_item_reads[suffix]
        self.per_item_reads[suffix] += 1
        value = self.inventories[suffix][index]
        record = {"id": item_id, "sku": f"AUTO-{suffix}", "tracked": True,
                  "inventoryLevel": {"id": "gid://shopify/InventoryLevel/1",
                    "isActive": True, "location": {"id": location_id,
                    "name": "Test location", "isActive": True},
                    "quantities": [{"name": "available", "quantity": value}]}}
        if self.bad_field:
            item_key, new_value = self.bad_field
            record[item_key] = new_value
        return {"inventoryItem": record}


class Resolver:
    def resolve(self, shopify_variant_id):
        suffix = shopify_variant_id.rsplit("/", 1)[-1]
        return ShopifyInventoryTarget(
            inventory_item_id=f"gid://shopify/InventoryItem/{suffix}",
            location_id=LOCATION,
        )


def workflow(*, approved=True):
    decisions = []
    for suffix, baseline, proposed in (("1001", 25, 26), ("1002", 40, 42)):
        decisions.append(SupplierSyncDecision(
            supplier_code="demo_supplier", supplier_sku=f"SUP-{suffix}",
            shopify_variant_id=f"gid://shopify/ProductVariant/{suffix}",
            shopify_sku=f"AUTO-{suffix}",
            status=SyncDecisionStatus.ELIGIBLE,
            reason=SyncDecisionReason.INVENTORY_MISMATCH_WITHIN_LIMIT,
            current_inventory_quantity=baseline,
            supplier_inventory_quantity=proposed,
            inventory_delta=proposed-baseline,
            proposed_inventory_quantity=proposed,
        ))
    plan = build_dry_run_sync_plan(decisions)
    manifest = build_batch_safety_manifest(
        plan=plan, policy=BatchSafetyPolicy(
            max_mutations_per_batch=5, max_total_absolute_inventory_delta=100,
            max_single_item_absolute_delta=50,
        ),
    )
    approval = evaluate_batch_approval(
        plan=plan, manifest=manifest,
        approved_manifest_fingerprint=manifest.manifest_fingerprint if approved else None,
    )
    return dict(expected_shop_id=GID, expected_location_id=LOCATION,
                plan=plan, manifest=manifest, approval_report=approval,
                target_resolver=Resolver())


def inspect(fake=None, **changes):
    client = fake if fake is not None else ShopAndInventoryFake()
    kwargs = workflow()
    kwargs.update(changes)
    return inspect_pinned_live_candidate(client=client, **kwargs), client


def assert_never_executes(report):
    assert report.live_execution_allowed is False
    assert report.automatic_retry_allowed is False
    assert report.operator_authenticated is False


def test_pinned_shop_and_four_realistic_inventory_reads():
    report, fake = inspect()
    assert report.status is PinnedReadOnlyStatus.BASELINES_MATCH
    assert report.shop_id == GID and report.shop_domain == SHOP
    assert report.shop_identity_reads == 2 and report.inventory_reads == 4
    assert [kind for kind, _ in fake.calls] == [
        SHOP_IDENTITY_QUERY, INVENTORY_READBACK_QUERY, INVENTORY_READBACK_QUERY,
        INVENTORY_READBACK_QUERY, INVENTORY_READBACK_QUERY, SHOP_IDENTITY_QUERY,
    ]
    assert len(report.inspected_items) == 2
    assert report.can_continue_to_operator_review
    assert re.fullmatch("[0-9a-f]{64}", report.inspection_fingerprint)
    assert_never_executes(report)


def test_unapproved_manifest_makes_zero_shopify_calls():
    fake = ShopAndInventoryFake()
    args = workflow(approved=False)
    report = inspect_pinned_live_candidate(client=fake, **args)
    assert report.status is PinnedReadOnlyStatus.APPROVAL_REQUIRED
    assert fake.calls == []
    assert_never_executes(report)


@pytest.mark.parametrize("bad", ["", None, True, "gid://shopify/Shop/0", "gid://shopify/Product/99", "gid://shopify/Shop/xyz"])
def test_invalid_shop_pin_never_calls_network(bad):
    report, fake = inspect(expected_shop_id=bad)
    assert report.status is PinnedReadOnlyStatus.INVALID_SCOPE
    assert fake.calls == []
    assert_never_executes(report)


@pytest.mark.parametrize("bad", ["", None, 42, "gid://shopify/Location/0", "gid://shopify/Shop/33"])
def test_invalid_location_never_calls_network(bad):
    report, fake = inspect(expected_location_id=bad)
    assert report.status is PinnedReadOnlyStatus.INVALID_SCOPE
    assert fake.calls == []


def test_mismatched_initial_shop_blocks_before_inventory():
    report, fake = inspect(ShopAndInventoryFake(shop_ids=(WRONG_GID, GID)))
    assert report.status is PinnedReadOnlyStatus.SHOP_UNAVAILABLE_OR_MISMATCH
    assert report.shop_id is None
    assert len(fake.calls) == 1
    assert report.shop_identity_reads == 1
    assert fake.calls[0][0] == SHOP_IDENTITY_QUERY
    assert_never_executes(report)


@pytest.mark.parametrize("bad", ["another.myshopify.com", "integration-test.myshopify.com.evil.test"])
def test_mismatched_initial_domain_blocks_before_inventory(bad):
    report, fake = inspect(ShopAndInventoryFake(shop_domains=(bad, SHOP)))
    assert report.status is PinnedReadOnlyStatus.SHOP_UNAVAILABLE_OR_MISMATCH
    assert len(fake.calls) == 1


def test_shop_change_after_four_reads_is_detected():
    report, fake = inspect(ShopAndInventoryFake(shop_ids=(GID, WRONG_GID)))
    assert report.status is PinnedReadOnlyStatus.SHOP_CHANGED_DURING_REVIEW
    assert report.inventory_reads == 4 and report.shop_identity_reads == 2
    assert not report.can_continue_to_operator_review
    assert_never_executes(report)


def test_shop_domain_change_after_four_reads_is_detected():
    report, _ = inspect(ShopAndInventoryFake(shop_domains=(SHOP, "other.myshopify.com")))
    assert report.status is PinnedReadOnlyStatus.SHOP_CHANGED_DURING_REVIEW


@pytest.mark.parametrize("target", ["1001", "1002"])
def test_preflight_detects_inventory_drift(target):
    quantities = {"1001": (25, 25), "1002": (40, 40)}
    quantities[target] = (BASELINES[target] - 1, BASELINES[target])
    report, fake = inspect(ShopAndInventoryFake(inventories=quantities))
    assert report.status is PinnedReadOnlyStatus.PREFLIGHT_BLOCKED
    assert not report.can_continue_to_operator_review
    assert fake.identities == 1
    assert_never_executes(report)


@pytest.mark.parametrize("target", ["1001", "1002"])
def test_second_read_detects_drift(target):
    quantities = {"1001": (25, 25), "1002": (40, 40)}
    quantities[target] = (BASELINES[target], BASELINES[target] - 1)
    report, fake = inspect(ShopAndInventoryFake(inventories=quantities))
    assert report.status is PinnedReadOnlyStatus.INVENTORY_STALE
    assert fake.identities == 1
    assert not report.inspection_fingerprint
    assert_never_executes(report)


@pytest.mark.parametrize("call_index,expected_status", [
    (1, PinnedReadOnlyStatus.SHOP_UNAVAILABLE_OR_MISMATCH),
    (2, PinnedReadOnlyStatus.PREFLIGHT_BLOCKED),
    (3, PinnedReadOnlyStatus.PREFLIGHT_BLOCKED),
    (4, PinnedReadOnlyStatus.SECOND_READ_BLOCKED),
    (5, PinnedReadOnlyStatus.SECOND_READ_BLOCKED),
    (6, PinnedReadOnlyStatus.SHOP_CHANGED_DURING_REVIEW),
])
def test_network_exception_fails_closed_and_sanitized(call_index, expected_status):
    report, fake = inspect(ShopAndInventoryFake(fail_at=call_index))
    assert report.status is expected_status
    assert "SENSITIVE" not in str(report)
    assert not report.can_continue_to_operator_review
    assert_never_executes(report)


@pytest.mark.parametrize("value", ["false", 1, None])
def test_invalid_tracked_flag_rejected_in_query_fence(value):
    report, fake = inspect(ShopAndInventoryFake(bad_field=("tracked", value)))
    assert report.status is PinnedReadOnlyStatus.PREFLIGHT_BLOCKED
    assert not report.can_continue_to_operator_review
    assert_never_executes(report)


def test_session_rejects_mutation_and_arbitrary_queries_without_network():
    fake = ShopAndInventoryFake()
    session = PinnedReadOnlySession(fake, expected_shop_id=GID)
    session.verify_shop_before()
    before = len(fake.calls)
    for query in (INVENTORY_SET_QUANTITIES, "mutation { inventorySetQuantities }",
                  "query { products(first: 1) { nodes { id } } }", SHOP_IDENTITY_QUERY):
        with pytest.raises(ReadOnlyQueryRejected):
            session.graphql(query, {})
    assert len(fake.calls) == before
    assert not hasattr(session, "send")


def test_session_rejects_read_before_shop_identity():
    fake = ShopAndInventoryFake()
    session = PinnedReadOnlySession(fake, expected_shop_id=GID)
    with pytest.raises(ReadOnlyQueryRejected):
        session.graphql(INVENTORY_READBACK_QUERY, {
            "inventoryItemId": "gid://shopify/InventoryItem/1001", "locationId": LOCATION,
        })
    assert fake.calls == []


def test_session_prevents_duplicate_identity_and_early_finalization():
    fake = ShopAndInventoryFake()
    session = PinnedReadOnlySession(fake, expected_shop_id=GID)
    session.verify_shop_before()
    with pytest.raises(ReadOnlyQueryRejected):
        session.verify_shop_before()
    with pytest.raises(ReadOnlyQueryRejected):
        session.verify_shop_after()
    assert len(fake.calls) == 1


def test_session_rejects_fifth_inventory_read_after_four():
    fake = ShopAndInventoryFake()
    session = PinnedReadOnlySession(fake, expected_shop_id=GID)
    session.verify_shop_before()
    for suffix in ("1001", "1002", "1001", "1002"):
        session.graphql(INVENTORY_READBACK_QUERY, {
            "inventoryItemId": f"gid://shopify/InventoryItem/{suffix}", "locationId": LOCATION,
        })
    with pytest.raises(ReadOnlyQueryRejected):
        session.graphql(INVENTORY_READBACK_QUERY, {
            "inventoryItemId": "gid://shopify/InventoryItem/1001", "locationId": LOCATION,
        })
    assert session.inventory_reads == 4 and len(fake.calls) == 5
    session.verify_shop_after()
    with pytest.raises(ReadOnlyQueryRejected):
        session.graphql(INVENTORY_READBACK_QUERY, {
            "inventoryItemId": "gid://shopify/InventoryItem/1001", "locationId": LOCATION,
        })
    assert len(fake.calls) == 6


def test_fingerprint_differs_if_authenticated_shop_id_differs():
    report_a, _ = inspect()
    alternate_gid = "gid://shopify/Shop/33333"
    alternate = ShopAndInventoryFake(shop_ids=(alternate_gid, alternate_gid))
    report_b, _ = inspect(alternate, expected_shop_id=alternate_gid)
    assert report_b.status is PinnedReadOnlyStatus.BASELINES_MATCH
    assert report_a.inspection_fingerprint != report_b.inspection_fingerprint


def test_wrong_approval_fingerprint_rejected_before_inventory():
    data = workflow()
    data["approval_report"] = replace(data["approval_report"], approved_manifest_fingerprint="0" * 64)
    report, fake = inspect(**data)
    assert report.status is PinnedReadOnlyStatus.PREFLIGHT_BLOCKED
    assert fake.identities == 1
    assert fake.per_item_reads == {"1001": 0, "1002": 0}


def test_shop_query_failure_counts_attempt_without_leaking_error():
    report, fake = inspect(ShopAndInventoryFake(fail_at=1))
    assert report.status is PinnedReadOnlyStatus.SHOP_UNAVAILABLE_OR_MISMATCH
    assert report.shop_identity_reads == 1 and report.inventory_reads == 0
    assert len(fake.calls) == 1
    assert "SENSITIVE" not in repr(report)


def test_first_shop_identity_report_never_exposes_unpinned_gid():
    report, fake = inspect(ShopAndInventoryFake(shop_ids=(WRONG_GID, GID)))
    assert report.shop_id is None and report.shop_domain is None
    assert report.shop_identity_reads == 1
    assert_never_executes(report)
