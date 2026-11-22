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
from supplier.batch.approval import evaluate_batch_approval  # noqa: E402
from supplier.batch.builder import build_batch_safety_manifest  # noqa: E402
from supplier.batch.models import BatchSafetyPolicy  # noqa: E402
from supplier.decision.models import (  # noqa: E402
    SupplierSyncDecision,
    SyncDecisionReason,
    SyncDecisionStatus,
)
from supplier.execution.readback import ShopifyInventoryReadbackAdapter  # noqa: E402
from supplier.execution.shopify_adapter import (  # noqa: E402
    SQLiteInventoryTargetResolver,
)
from supplier.mapping.json_loader import JsonSupplierMappingLoader  # noqa: E402
from supplier.plan.builder import build_dry_run_sync_plan  # noqa: E402
from supplier.preflight.service import evaluate_live_batch_preflight  # noqa: E402


SUPPLIER_CODE = "demo_supplier"

BATCH_POLICY = BatchSafetyPolicy(
    max_mutations_per_batch=5,
    max_total_absolute_inventory_delta=100,
    max_single_item_absolute_delta=50,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Build an approved two-item READ-ONLY candidate and compare its "
            "trusted V1 baseline with fresh live Shopify quantities."
        )
    )

    parser.add_argument(
        "--location-id",
        required=True,
        help=(
            "Exact Shopify Location GID previously verified during V2.5C."
        ),
    )

    parser.add_argument(
        "--approve-manifest",
        default=None,
        help=(
            "Exact manifest fingerprint printed during PREPARE."
        ),
    )

    return parser.parse_args()


def build_read_only_candidate():
    """
    Create a two-item synthetic proposal from trusted V1 SQLite baselines.

    The proposed quantities are intentionally small (+1, +2), but this script
    NEVER executes them. The purpose is only to prove the live preflight guard.
    """

    mapping_path = (
        PROJECT_ROOT
        / "supplier"
        / "samples"
        / "sample_supplier_mappings.json"
    )

    mappings = [
        mapping
        for mapping
        in (
            JsonSupplierMappingLoader(
                mapping_path
            )
            .load_registry()
            .list_mappings(
                active_only=True
            )
        )
        if (
            mapping.supplier_code
            == SUPPLIER_CODE
        )
    ]

    rows_by_variant = {}

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                shopify_variant_id,
                sku,
                inventory_quantity,
                inventory_item_id
            FROM variants
            WHERE inventory_item_id IS NOT NULL
              AND TRIM(inventory_item_id) <> '';
            """
        ).fetchall()

    for row in rows:
        data = dict(row)
        rows_by_variant[
            data["shopify_variant_id"]
        ] = data

    candidates = []

    for mapping in sorted(
        mappings,
        key=lambda item: (
            item.shopify_sku,
            item.shopify_variant_id,
        ),
    ):
        row = rows_by_variant.get(
            mapping.shopify_variant_id
        )

        if row is None:
            continue

        current = row.get(
            "inventory_quantity"
        )

        if (
            isinstance(current, bool)
            or not isinstance(current, int)
        ):
            continue

        candidates.append(
            (
                mapping,
                current,
            )
        )

    if len(candidates) < 2:
        raise RuntimeError(
            "V2.8A live preflight requires at least two mapped variants "
            "with trusted V1 inventory baselines."
        )

    decisions = []

    for index, (
        mapping,
        current,
    ) in enumerate(
        candidates[:2],
        start=1,
    ):
        proposed = (
            current
            + index
        )

        decisions.append(
            SupplierSyncDecision(
                supplier_code=(
                    mapping.supplier_code
                ),
                supplier_sku=(
                    mapping.supplier_sku
                ),
                shopify_variant_id=(
                    mapping.shopify_variant_id
                ),
                shopify_sku=(
                    mapping.shopify_sku
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

    plan = build_dry_run_sync_plan(
        decisions
    )

    manifest = build_batch_safety_manifest(
        plan=plan,
        policy=BATCH_POLICY,
    )

    return (
        plan,
        manifest,
    )


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

    plan, manifest = (
        build_read_only_candidate()
    )

    approval = evaluate_batch_approval(
        plan=plan,
        manifest=manifest,
        approved_manifest_fingerprint=(
            args.approve_manifest
        ),
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.8A LIVE BATCH PREFLIGHT + DRIFT GUARD"
    )
    print("=" * 72)
    print(
        "MODE: READ ONLY"
    )
    print(
        "CANDIDATE SOURCE: TRUSTED V1 SQLITE BASELINE + SYNTHETIC PROPOSAL"
    )
    print(
        "SUPPLIER FEED EXECUTION: DISABLED"
    )
    print(
        "SHOPIFY MUTATIONS: DISABLED"
    )
    print(
        "SQLITE WRITES: 0"
    )
    print("-" * 72)

    print(
        "CANDIDATE BATCH"
    )
    print("-" * 72)

    for index, item in enumerate(
        manifest.mutations,
        start=1,
    ):
        print(
            f"Item #{index}"
        )
        print(
            f"  Supplier SKU: "
            f"{item.supplier_sku}"
        )
        print(
            f"  Shopify SKU: "
            f"{item.shopify_sku}"
        )
        print(
            f"  Variant: "
            f"{item.shopify_variant_id}"
        )
        print(
            f"  Approved baseline: "
            f"{item.current_inventory_quantity}"
        )
        print(
            f"  Synthetic proposed: "
            f"{item.proposed_inventory_quantity}"
        )
        print(
            f"  Delta: "
            f"{item.inventory_delta:+d}"
        )

    print("-" * 72)
    print(
        "Plan fingerprint:"
    )
    print(
        plan.fingerprint
    )
    print(
        "Manifest fingerprint:"
    )
    print(
        manifest.manifest_fingerprint
    )
    print(
        f"Approval status: "
        f"{approval.status.value.upper()}"
    )
    print("-" * 72)

    if not approval.can_execute:
        print(
            "PREFLIGHT STATUS: APPROVAL_REQUIRED"
        )
        print(
            "LIVE SHOPIFY READS PERFORMED: 0"
        )
        print(
            "LIVE SHOPIFY WRITES PERFORMED: 0"
        )
        print()
        print(
            "Re-run with:"
        )
        print(
            "python scripts/"
            "supplier_live_batch_preflight.py "
            f"--location-id {args.location_id} "
            "--approve-manifest "
            f"{manifest.manifest_fingerprint}"
        )
        return 0

    print(
        "Authenticating with Shopify for fresh READ-ONLY inventory checks..."
    )

    client = build_client()

    resolver = SQLiteInventoryTargetResolver(
        location_id=(
            args.location_id
        )
    )

    readback = (
        ShopifyInventoryReadbackAdapter(
            client
        )
    )

    report = evaluate_live_batch_preflight(
        plan=plan,
        manifest=manifest,
        approval_report=approval,
        target_resolver=resolver,
        readback_port=readback,
        expected_location_id=(
            args.location_id
        ),
    )

    print()
    print(
        "FRESH SHOPIFY PREFLIGHT"
    )
    print("-" * 72)

    for item in report.items:
        print(
            f"Item #{item.item_index} "
            f"| {item.shopify_sku}"
        )
        print(
            f"  Inventory item: "
            f"{item.inventory_item_id}"
        )
        print(
            f"  Location: "
            f"{item.location_id}"
        )
        print(
            f"  Approved baseline: "
            f"{item.approved_baseline_quantity}"
        )
        print(
            f"  Fresh Shopify: "
            f"{item.fresh_shopify_quantity}"
        )
        print(
            f"  Proposed: "
            f"{item.proposed_inventory_quantity}"
        )
        print(
            f"  Status: "
            f"{item.status.value.upper()}"
        )
        print(
            "  Reasons: "
            + ", ".join(
                reason.value
                for reason
                in item.reasons
            )
        )

        if item.error_message:
            print(
                f"  Error: "
                f"{item.error_message}"
            )

    print("-" * 72)
    print(
        f"PREFLIGHT STATUS: "
        f"{report.status.value.upper()}"
    )
    print(
        "Preflight reasons: "
        + ", ".join(
            reason.value
            for reason
            in report.reasons
        )
    )
    print(
        f"Ready items: "
        f"{report.ready_items}"
    )
    print(
        f"Stale items: "
        f"{report.stale_items}"
    )
    print(
        f"Blocked items: "
        f"{report.blocked_items}"
    )
    print(
        "Preflight fingerprint:"
    )
    print(
        report.preflight_fingerprint
    )
    print()
    print(
        f"FUTURE EXECUTION ALLOWED BY PREFLIGHT: "
        f"{report.can_execute}"
    )
    print(
        "LIVE SHOPIFY WRITES PERFORMED: 0"
    )
    print(
        "SQLITE WRITES PERFORMED: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
