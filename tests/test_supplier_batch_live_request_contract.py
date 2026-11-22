"""Offline tests: no Shopify client or SQLite dependency."""

from dataclasses import replace
from uuid import uuid4

import pytest

from supplier.batch.live_request_contract import (
    CandidateQuantity,
    ContractRejected,
    INVENTORY_SET_QUANTITIES,
    PreflightEvidence,
    prepare_mutation_preview,
)


@pytest.fixture
def evidence():
    return PreflightEvidence("a" * 64, "b" * 64, "b" * 64, "c" * 64, "READY", 2, 0, 0)


@pytest.fixture
def items():
    return (
        CandidateQuantity("DEMO-CAP", "gid://shopify/InventoryItem/1001", "gid://shopify/Location/100", 25, 25, 26),
        CandidateQuantity("DEMO-SHIRT", "gid://shopify/InventoryItem/1002", "gid://shopify/Location/100", 40, 40, 42),
    )


def build(evidence, items, operation_id=None):
    return prepare_mutation_preview(evidence, items, operation_id=operation_id or str(uuid4()))


def test_build_two_item_preview(evidence, items):
    result = build(evidence, items)
    assert result.mode == "OFFLINE_PREVIEW_ONLY"
    assert len(result.variables["input"]["quantities"]) == 2
    assert not hasattr(result, "execute")


def test_api_requires_cas_and_idempotency(evidence, items):
    result = build(evidence, items)
    assert "@idempotent(key: $idempotencyKey)" in INVENTORY_SET_QUANTITIES
    assert result.variables["idempotencyKey"] == result.operation_id
    assert result.variables["input"]["name"] == "available"
    assert result.variables["input"]["quantities"][0]["changeFromQuantity"] == 25
    assert all(q["changeFromQuantity"] is not None for q in result.variables["input"]["quantities"])
    assert "ignoreCompareQuantity" not in result.variables["input"]


def test_identical_operation_and_candidates_produce_identical_request(evidence, items):
    operation_id = str(uuid4())
    one = build(evidence, items, operation_id)
    two = build(evidence, tuple(reversed(items)), operation_id)
    assert one.variables == two.variables
    assert one.skus == two.skus


@pytest.mark.parametrize("field,value", [
    ("status", "STALE"),
    ("status", "BLOCKED"),
    ("status", "APPROVAL_REQUIRED"),
    ("ready_items", 1),
    ("stale_items", 1),
    ("blocked_items", 1),
    ("approved_manifest_fingerprint", "d" * 64),
    ("preflight_fingerprint", "not-a-hash"),
    ("plan_fingerprint", "A" * 64),
])
def test_reject_invalid_preflight(evidence, items, field, value):
    with pytest.raises(ContractRejected):
        build(replace(evidence, **{field: value}), items)


@pytest.mark.parametrize("field,value", [
    ("fresh", 24),
    ("baseline", -1),
    ("fresh", None),
    ("proposed", True),
    ("proposed", 25),
    ("proposed", 28),
    ("sku", ""),
    ("inventory_item_id", "123"),
    ("location_id", "gid://shopify/Location/0"),
])
def test_reject_unsafe_item(evidence, items, field, value):
    with pytest.raises(ContractRejected):
        build(evidence, (replace(items[0], **{field: value}), items[1]))


def test_reject_duplicate_inventory_id(evidence, items):
    with pytest.raises(ContractRejected):
        build(evidence, (items[0], replace(items[1], inventory_item_id=items[0].inventory_item_id)))


def test_reject_duplicate_sku(evidence, items):
    with pytest.raises(ContractRejected):
        build(evidence, (items[0], replace(items[1], sku=items[0].sku)))


def test_reject_different_locations(evidence, items):
    with pytest.raises(ContractRejected):
        build(evidence, (items[0], replace(items[1], location_id="gid://shopify/Location/101")))


def test_reject_non_two_item_batch(evidence, items):
    with pytest.raises(ContractRejected):
        build(evidence, items[:1])


def test_reject_wrong_collection_type(evidence, items):
    with pytest.raises(ContractRejected):
        build(evidence, list(items))


def test_reject_non_uuid_operation_id(evidence, items):
    with pytest.raises(ContractRejected):
        build(evidence, items, "not-a-uuid")


def test_reject_non_v4_operation_id(evidence, items):
    with pytest.raises(ContractRejected):
        build(evidence, items, "00000000-0000-5000-8000-000000000000")


def test_reject_non_evidence_object(items):
    with pytest.raises(ContractRejected):
        build({}, items)
