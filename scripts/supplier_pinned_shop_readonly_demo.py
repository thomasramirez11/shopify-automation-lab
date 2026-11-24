"""V2.8B/11 OFFLINE shop-pinned controller proof (no credentials or SQLite)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supplier.batch.approval import evaluate_batch_approval
from supplier.batch.builder import build_batch_safety_manifest
from supplier.batch.live_pinned_readonly_controller import inspect_pinned_live_candidate
from supplier.batch.live_store_identity import SHOP_IDENTITY_QUERY
from supplier.batch.models import BatchSafetyPolicy
from supplier.decision.models import SupplierSyncDecision, SyncDecisionReason, SyncDecisionStatus
from supplier.execution.readback import INVENTORY_READBACK_QUERY
from supplier.execution.shopify_adapter import ShopifyInventoryTarget
from supplier.plan.builder import build_dry_run_sync_plan

SHOP = "local-demo.myshopify.com"
SHOP_ID = "gid://shopify/Shop/12345"
LOCATION = "gid://shopify/Location/9001"


class FakeShopify:
    store_domain = SHOP

    def __init__(self, *, wrong_shop=False, stale=False):
        self.calls = []
        self.wrong_shop = wrong_shop
        self.stale = stale
        self.item_reads = {}

    def graphql(self, query, variables):
        self.calls.append(query)
        if query == SHOP_IDENTITY_QUERY:
            return {"shop": {"id": "gid://shopify/Shop/99999" if self.wrong_shop else SHOP_ID,
                             "myshopifyDomain": SHOP}}
        assert query == INVENTORY_READBACK_QUERY  # The fake rejects any other operation.
        sku_id = variables["inventoryItemId"].split("/")[-1]
        self.item_reads[sku_id] = self.item_reads.get(sku_id, 0) + 1
        current = {"1001": 25, "1002": 40}[sku_id]
        if self.stale and sku_id == "1002" and self.item_reads[sku_id] == 2:
            current -= 1
        return {"inventoryItem": {
            "id": variables["inventoryItemId"], "sku": f"AUTO-{sku_id}", "tracked": True,
            "inventoryLevel": {"id": "gid://shopify/InventoryLevel/1", "isActive": True,
                "location": {"id": variables["locationId"], "name": "Demo", "isActive": True},
                "quantities": [{"name": "available", "quantity": current}]},
        }}


class Resolver:
    def resolve(self, shopify_variant_id):
        sku_id = shopify_variant_id.rsplit("/", 1)[-1]
        return ShopifyInventoryTarget(
            inventory_item_id=f"gid://shopify/InventoryItem/{sku_id}",
            location_id=LOCATION,
        )


def build():
    decisions = []
    for sku, before, after in (("1001", 25, 26), ("1002", 40, 42)):
        decisions.append(SupplierSyncDecision(
            supplier_code="demo_supplier", supplier_sku="SUP-" + sku,
            shopify_variant_id="gid://shopify/ProductVariant/" + sku,
            shopify_sku="AUTO-" + sku,
            status=SyncDecisionStatus.ELIGIBLE,
            reason=SyncDecisionReason.INVENTORY_MISMATCH_WITHIN_LIMIT,
            current_inventory_quantity=before,
            supplier_inventory_quantity=after,
            inventory_delta=after - before,
            proposed_inventory_quantity=after,
        ))
    plan = build_dry_run_sync_plan(decisions)
    manifest = build_batch_safety_manifest(plan=plan, policy=BatchSafetyPolicy(
        max_mutations_per_batch=5, max_total_absolute_inventory_delta=100,
        max_single_item_absolute_delta=50,
    ))
    approval = evaluate_batch_approval(plan=plan, manifest=manifest,
                                       approved_manifest_fingerprint=manifest.manifest_fingerprint)
    return plan, manifest, approval


def main() -> int:
    plan, manifest, approval = build()
    outputs = {}
    for name, fake in (
        ("UNCHANGED", FakeShopify()),
        ("WRONG_SHOP", FakeShopify(wrong_shop=True)),
        ("SECOND_READ_DRIFT", FakeShopify(stale=True)),
    ):
        report = inspect_pinned_live_candidate(
            client=fake, expected_shop_id=SHOP_ID, expected_location_id=LOCATION,
            plan=plan, manifest=manifest, approval_report=approval,
            target_resolver=Resolver(),
        )
        outputs[name] = report.status.value
        assert not report.live_execution_allowed and not report.automatic_retry_allowed
        print(f"CASE {name}: {report.status.value} | SHOP READS {report.shop_identity_reads} "
              f"| INVENTORY READS {report.inventory_reads}")
    assert outputs == {
        "UNCHANGED": "BASELINES_MATCH",
        "WRONG_SHOP": "SHOP_UNAVAILABLE_OR_MISMATCH",
        "SECOND_READ_DRIFT": "INVENTORY_STALE",
    }
    print("REAL SHOPIFY NETWORK CALLS: 0")
    print("LIVE SHOPIFY WRITES: 0")
    print("PROJECT SQLITE WRITES: 0")
    print("STATUS: PINNED SHOP READ-ONLY CONTROLLER VERIFIED — EXECUTION DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
