from __future__ import annotations

import argparse
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


from config.settings import (  # noqa: E402
    SHOPIFY_API_VERSION,
    SHOPIFY_CLIENT_ID,
    SHOPIFY_CLIENT_SECRET,
    SHOPIFY_STORE_DOMAIN,
)
from database.connection import get_db_connection  # noqa: E402
from shopify.client import ShopifyClient  # noqa: E402
from supplier.adapters.json_file_supplier import JsonFileSupplierAdapter  # noqa: E402
from supplier.comparison.engine import compare_supplier_to_shopify  # noqa: E402
from supplier.comparison.snapshot import (  # noqa: E402
    SQLiteShopifyComparisonSnapshotAdapter,
)
from supplier.decision.models import InventorySyncPolicy  # noqa: E402
from supplier.decision.policy import evaluate_supplier_sync_decision  # noqa: E402
from supplier.execution.live_controller import (  # noqa: E402
    build_live_confirmation_token,
    execute_controlled_single_variant_write,
    verify_pre_write_state,
)
from supplier.execution.readback import ShopifyInventoryReadbackAdapter  # noqa: E402
from supplier.execution.safety import (  # noqa: E402
    LIVE_WRITE_ENV_VAR,
    live_writes_enabled_from_environment,
)
from supplier.execution.shopify_adapter import (  # noqa: E402
    SQLiteInventoryTargetResolver,
    ShopifyInventoryMutationAdapter,
)
from supplier.guard.guard import evaluate_execution_guard  # noqa: E402
from supplier.mapping.json_loader import JsonSupplierMappingLoader  # noqa: E402
from supplier.plan.builder import build_dry_run_sync_plan  # noqa: E402


SUPPLIER_CODE = "demo_supplier"
MAX_INVENTORY_DELTA = 50


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or execute exactly one supplier-driven Shopify "
            "inventory mutation."
        )
    )

    parser.add_argument(
        "--target-sku",
        required=True,
        help="Exactly one mapped Shopify SKU.",
    )

    parser.add_argument(
        "--location-id",
        required=True,
        help="Exact Shopify Location GID discovered during V2.5C.",
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Enter the execution path. The environment kill switch, exact "
            "fingerprint approval, and confirmation token are still required."
        ),
    )

    parser.add_argument(
        "--approve-fingerprint",
        default=None,
        help="Exact one-item plan fingerprint printed during PREPARE.",
    )

    parser.add_argument(
        "--confirm",
        default=None,
        help="Exact human confirmation token printed during PREPARE.",
    )

    return parser.parse_args()


def load_inventory_item_id(
    shopify_variant_id: str,
) -> str:
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT inventory_item_id
            FROM variants
            WHERE shopify_variant_id = ?;
            """,
            (
                shopify_variant_id,
            ),
        ).fetchone()

    if row is None:
        raise RuntimeError(
            "Mapped Shopify variant is missing from SQLite."
        )

    inventory_item_id = dict(row).get(
        "inventory_item_id"
    )

    if (
        not isinstance(inventory_item_id, str)
        or not inventory_item_id.strip()
    ):
        raise RuntimeError(
            "Mapped Shopify variant has no InventoryItem ID."
        )

    return inventory_item_id.strip()


def build_single_target_plan(
    *,
    target_sku: str,
):
    supplier_feed_path = (
        PROJECT_ROOT
        / "supplier"
        / "samples"
        / "sample_supplier_feed.json"
    )

    mapping_feed_path = (
        PROJECT_ROOT
        / "supplier"
        / "samples"
        / "sample_supplier_mappings.json"
    )

    supplier_adapter = JsonFileSupplierAdapter(
        supplier_feed_path
    )

    mapping_registry = (
        JsonSupplierMappingLoader(
            mapping_feed_path
        )
        .load_registry()
    )

    snapshot_adapter = (
        SQLiteShopifyComparisonSnapshotAdapter()
    )

    policy = InventorySyncPolicy(
        max_inventory_delta=(
            MAX_INVENTORY_DELTA
        )
    )

    supplier_products = {
        product.supplier_sku: product
        for product in supplier_adapter.list_products()
    }

    matching_mappings = [
        mapping
        for mapping in (
            mapping_registry.list_mappings(
                active_only=True
            )
        )
        if (
            mapping.supplier_code
            == SUPPLIER_CODE
            and mapping.shopify_sku
            == target_sku
        )
    ]

    if len(matching_mappings) != 1:
        raise RuntimeError(
            "Target SKU must resolve to exactly one active supplier mapping."
        )

    mapping = matching_mappings[0]

    supplier_product = supplier_products.get(
        mapping.supplier_sku
    )

    snapshot = snapshot_adapter.get_snapshot(
        mapping.shopify_variant_id
    )

    comparison = compare_supplier_to_shopify(
        mapping=mapping,
        supplier_product=supplier_product,
        shopify_variant=(
            snapshot.shopify_variant
            if snapshot is not None
            else None
        ),
        stored_cost=(
            snapshot.stored_cost
            if snapshot is not None
            else None
        ),
    )

    decision = evaluate_supplier_sync_decision(
        comparison=comparison,
        policy=policy,
    )

    plan = build_dry_run_sync_plan(
        [
            decision
        ]
    )

    return mapping, plan


def build_client():
    client = ShopifyClient(
        store_domain=SHOPIFY_STORE_DOMAIN,
        client_id=SHOPIFY_CLIENT_ID,
        client_secret=SHOPIFY_CLIENT_SECRET,
        api_version=SHOPIFY_API_VERSION,
    )

    client.authenticate()

    return client


def main() -> int:
    args = parse_args()

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2 FIRST CONTROLLED LIVE INVENTORY WRITE"
    )
    print("=" * 76)

    mapping, plan = build_single_target_plan(
        target_sku=args.target_sku,
    )

    if len(plan.items) != 1:
        raise RuntimeError(
            "Controlled write requires exactly one plan item."
        )

    item = plan.items[0]

    inventory_item_id = load_inventory_item_id(
        mapping.shopify_variant_id
    )

    client = build_client()

    readback = ShopifyInventoryReadbackAdapter(
        client
    )

    before = readback.read_available(
        inventory_item_id=inventory_item_id,
        location_id=args.location_id,
    )

    verify_pre_write_state(
        plan=plan,
        target_sku=args.target_sku,
        readback=before,
    )

    confirmation_token = build_live_confirmation_token(
        shopify_sku=item.shopify_sku,
        proposed_inventory_quantity=(
            item.proposed_inventory_quantity
        ),
    )

    print(
        f"Mode: "
        f"{'EXECUTE' if args.execute else 'PREPARE'}"
    )
    print(
        f"Target Shopify SKU: {item.shopify_sku}"
    )
    print(
        f"Shopify Variant: {item.shopify_variant_id}"
    )
    print(
        f"Inventory Item: {inventory_item_id}"
    )
    print(
        f"Location: {before.location_name}"
    )
    print(
        f"Location ID: {before.location_id}"
    )
    print(
        f"Live Shopify available now: "
        f"{before.available_quantity}"
    )
    print(
        f"Supplier proposed inventory: "
        f"{item.proposed_inventory_quantity}"
    )
    print(
        f"Inventory delta: {item.inventory_delta}"
    )
    print("One-item plan fingerprint:")
    print(plan.fingerprint)
    print("Required confirmation token:")
    print(confirmation_token)
    print("-" * 76)

    if not args.execute:
        print(
            "PREPARE STATUS: READY FOR HUMAN REVIEW"
        )
        print(
            "LIVE SHOPIFY WRITES: 0"
        )
        print(
            "SQLITE WRITES: 0"
        )
        return 0

    if not live_writes_enabled_from_environment():
        print(
            "EXECUTION BLOCKED: "
            f"{LIVE_WRITE_ENV_VAR} is not enabled."
        )
        print(
            "LIVE SHOPIFY WRITES: 0"
        )
        return 1

    guard = evaluate_execution_guard(
        plan=plan,
        approved_fingerprint=(
            args.approve_fingerprint
        ),
    )

    if not guard.can_execute:
        print(
            f"EXECUTION BLOCKED: "
            f"{guard.status.value.upper()}"
        )
        print(
            "LIVE SHOPIFY WRITES: 0"
        )
        return 1

    target_resolver = SQLiteInventoryTargetResolver(
        location_id=args.location_id
    )

    inventory_adapter = (
        ShopifyInventoryMutationAdapter(
            shopify_client=client,
            target_resolver=target_resolver,
            live_writes_enabled=True,
        )
    )

    result = execute_controlled_single_variant_write(
        plan=plan,
        guard_report=guard,
        target_sku=args.target_sku,
        inventory_item_id=inventory_item_id,
        location_id=args.location_id,
        confirmation_token=(
            args.confirm
            or ""
        ),
        inventory_port=inventory_adapter,
        readback_port=readback,
    )

    print(
        "LIVE WRITE RESULT: SUCCESS"
    )
    print(
        "Attempted mutations: "
        f"{result.execution_report.attempted_mutations}"
    )
    print(
        "Applied mutations: "
        f"{result.execution_report.applied_mutations}"
    )
    print(
        "Verified Shopify available quantity: "
        f"{result.readback.available_quantity}"
    )
    print(
        "LIVE SHOPIFY WRITES: 1"
    )
    print(
        "SQLITE WRITES: 0"
    )
    print()
    print(
        "NEXT: disable the live-write environment switch, "
        "then run read-only discovery and V1 synchronization."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
