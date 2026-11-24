"""V2.8B/10 offline exercise; no real Shopify access or project database writes."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.supplier_batch_recovery_synthetic_demo import FakeReadback, build_prepared
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService
from supplier.batch.live_review_acknowledgement import (
    ReviewAckStatus, review_with_authenticated_identity,
)
from supplier.batch.live_risk_budget import ControlledTestBudget
from supplier.batch.live_store_identity import SHOP_IDENTITY_QUERY, ShopifyStoreIdentityReadOnly

SHOP = "demo-test.myshopify.com"
SHOP_ID = "gid://shopify/Shop/1001"


class FakeShopify:
    store_domain = SHOP

    def __init__(self, *, shop_id: str = SHOP_ID):
        self.shop_id = shop_id
        self.calls = 0

    def graphql(self, query: str, variables: dict):
        assert query == SHOP_IDENTITY_QUERY and variables == {}
        self.calls += 1
        return {"shop": {"id": self.shop_id, "myshopifyDomain": SHOP}}


@contextmanager
def connect(path):
    db = sqlite3.connect(path)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    print("SHOPIFY AUTOMATION LAB — V2.8B/10 IDENTITY + HUMAN ACKNOWLEDGEMENT")
    print("MODE: OFFLINE SYNTHETIC / ISOLATED SQLITE")
    with TemporaryDirectory(prefix="v2_8b10_") as temp:
        path = Path(temp) / "test.sqlite3"
        connection = lambda: connect(path)
        prepared = build_prepared()
        service = SupplierLiveBatchRecoveryService(
            intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connection),
            recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connection),
        )
        service.prepare(prepared)
        budget = ControlledTestBudget(
            store_domain=SHOP, location_id=prepared.location_id,
            sku_inventory_items=(("DEMO-1001", "gid://shopify/InventoryItem/1001"),
                                 ("DEMO-1002", "gid://shopify/InventoryItem/1002")),
        )
        source = FakeShopify()
        options = dict(
            shop_identity=ShopifyStoreIdentityReadOnly(source),
            expected_shop_id=SHOP_ID, archive=ReadOnlyRecoveryArchive(path),
            operation_id=prepared.preview.operation_id,
            expected_plan_fingerprint=prepared.plan_fingerprint,
            expected_manifest_fingerprint=prepared.manifest_fingerprint,
            proposal_source="CONTROLLED_TEST_SYNTHETIC", budget=budget,
        )
        baseline = review_with_authenticated_identity(
            **options, readback_port=FakeReadback({"1001": 25, "1002": 40}),
        )
        assert baseline.status is ReviewAckStatus.ACKNOWLEDGEMENT_REQUIRED
        ack = review_with_authenticated_identity(
            **options, readback_port=FakeReadback({"1001": 25, "1002": 40}),
            operator_acknowledgement=baseline.expected_acknowledgement,
        )
        assert ack.status is ReviewAckStatus.ACKNOWLEDGED_FOR_FURTHER_REVIEW
        mismatch = review_with_authenticated_identity(
            **options,
            readback_port=FakeReadback({"1001": 25, "1002": 40}),
            operator_acknowledgement="WRONG",
        )
        assert mismatch.status is ReviewAckStatus.ACKNOWLEDGEMENT_MISMATCH
        stale = review_with_authenticated_identity(
            **options, readback_port=FakeReadback({"1001": 25, "1002": 39}),
            operator_acknowledgement=baseline.expected_acknowledgement,
        )
        assert stale.status is ReviewAckStatus.REVIEW_BLOCKED
        wrong_store = review_with_authenticated_identity(
            **{**options, "expected_shop_id": "gid://shopify/Shop/9999"},
            readback_port=FakeReadback({"1001": 25, "1002": 40}),
        )
        assert wrong_store.status is ReviewAckStatus.SHOP_ID_MISMATCH
        for label, result in (("REVIEW_REQUIRED", baseline), ("ACK_MATCH", ack),
                              ("WRONG_ACK", mismatch), ("STALE", stale),
                              ("WRONG_SHOP", wrong_store)):
            assert not result.live_execution_allowed and not result.automatic_retry_allowed
            print(f"CASE {label}: {result.status.value}")
        print("LIVE SHOPIFY WRITES: 0")
        print("REAL SHOPIFY NETWORK CALLS: 0")
        print("PROJECT SQLITE WRITES: 0")
        print("OPERATOR AUTHENTICATED: False")
        print("STATUS: STORE IDENTITY + ACK REVIEW VERIFIED — LIVE SENDER DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
