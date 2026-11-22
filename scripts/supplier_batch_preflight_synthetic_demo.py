from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


from supplier.batch.approval import evaluate_batch_approval  # noqa: E402
from supplier.batch.builder import build_batch_safety_manifest  # noqa: E402
from supplier.batch.models import BatchSafetyPolicy  # noqa: E402
from supplier.decision.models import (  # noqa: E402
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.execution.readback import InventoryReadbackState  # noqa: E402
from supplier.execution.shopify_adapter import ShopifyInventoryTarget  # noqa: E402
from supplier.plan.builder import build_dry_run_sync_plan  # noqa: E402
from supplier.preflight.service import evaluate_live_batch_preflight  # noqa: E402


LOCATION_ID = "gid://shopify/Location/999001"


class DemoResolver:
    def resolve(
        self,
        shopify_variant_id,
    ):
        suffix = (
            shopify_variant_id
            .rsplit("/", 1)[-1]
        )

        return ShopifyInventoryTarget(
            inventory_item_id=(
                "gid://shopify/InventoryItem/"
                + suffix
            ),
            location_id=LOCATION_ID,
        )


class DemoReadback:
    def __init__(
        self,
        quantities,
    ):
        self._quantities = (
            quantities
        )

    def read_available(
        self,
        *,
        inventory_item_id,
        location_id,
    ):
        quantity = self._quantities[
            inventory_item_id
        ]

        suffix = (
            inventory_item_id
            .rsplit("/", 1)[-1]
        )

        return InventoryReadbackState(
            inventory_item_id=(
                inventory_item_id
            ),
            sku=(
                f"DEMO-{suffix}"
            ),
            tracked=True,
            location_id=(
                location_id
            ),
            location_name=(
                "Demo Location"
            ),
            location_active=True,
            level_active=True,
            available_quantity=(
                quantity
            ),
        )


def build_plan():
    decisions = []

    for suffix, current, proposed in (
        ("1001", 10, 15),
        ("1002", 20, 25),
    ):
        decisions.append(
            SupplierSyncDecision(
                supplier_code=(
                    "demo_supplier"
                ),
                supplier_sku=(
                    f"SUP-{suffix}"
                ),
                shopify_variant_id=(
                    "gid://shopify/ProductVariant/"
                    + suffix
                ),
                shopify_sku=(
                    f"DEMO-{suffix}"
                ),
                status=(
                    SyncDecisionStatus.ELIGIBLE
                ),
                reason=(
                    SyncDecisionReason
                    .INVENTORY_MISMATCH_WITHIN_LIMIT
                ),
                current_inventory_quantity=(
                    current
                ),
                supplier_inventory_quantity=(
                    proposed
                ),
                inventory_delta=(
                    proposed
                    - current
                ),
                proposed_inventory_quantity=(
                    proposed
                ),
            )
        )

    return build_dry_run_sync_plan(
        decisions
    )


def run_case(
    *,
    label,
    quantities,
):
    plan = build_plan()

    manifest = (
        build_batch_safety_manifest(
            plan=plan,
            policy=(
                BatchSafetyPolicy()
            ),
        )
    )

    approval = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            manifest.manifest_fingerprint
        ),
    )

    report = evaluate_live_batch_preflight(
        plan=plan,
        manifest=manifest,
        approval_report=approval,
        target_resolver=DemoResolver(),
        readback_port=(
            DemoReadback(
                quantities
            )
        ),
        expected_location_id=(
            LOCATION_ID
        ),
    )

    print(
        label
    )
    print(
        f"  status="
        f"{report.status.value.upper()}"
    )
    print(
        f"  ready={report.ready_items}"
    )
    print(
        f"  stale={report.stale_items}"
    )
    print(
        f"  blocked={report.blocked_items}"
    )

    for item in report.items:
        print(
            f"  {item.shopify_sku}: "
            f"baseline={item.approved_baseline_quantity} "
            f"fresh={item.fresh_shopify_quantity} "
            f"status={item.status.value.upper()}"
        )


def main() -> int:
    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.8A SYNTHETIC PREFLIGHT DRIFT DEMO"
    )
    print("=" * 72)
    print(
        "SHOPIFY NETWORK CALLS: 0"
    )
    print(
        "SQLITE CALLS: 0"
    )
    print("-" * 72)

    run_case(
        label="CASE A — BASELINE UNCHANGED",
        quantities={
            "gid://shopify/InventoryItem/1001":
                10,
            "gid://shopify/InventoryItem/1002":
                20,
        },
    )

    print("-" * 72)

    run_case(
        label="CASE B — ONE ITEM DRIFTED",
        quantities={
            "gid://shopify/InventoryItem/1001":
                10,
            "gid://shopify/InventoryItem/1002":
                18,
        },
    )

    print("-" * 72)
    print(
        "EXPECTED:"
    )
    print(
        "CASE A -> READY"
    )
    print(
        "CASE B -> STALE"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
