from __future__ import annotations

import argparse
import hashlib
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


from supplier.batch.case_resolution_models import (  # noqa: E402
    CaseResolutionError,
    ResolutionCode,
)
from supplier.batch.case_resolution_repository import (  # noqa: E402
    SupplierCaseResolutionRepository,
)
from supplier.batch.case_resolution_service import (  # noqa: E402
    SupplierCaseResolutionService,
)
from supplier.batch.dead_letter_repository import (  # noqa: E402
    SupplierDeadLetterRepository,
)
from supplier.batch.dead_letter_service import (  # noqa: E402
    SupplierDeadLetterService,
)
from supplier.batch.retry_models import (  # noqa: E402
    RetryAuditEvent,
    RetryEventType,
)
from supplier.batch.retry_repository import (  # noqa: E402
    SupplierBatchRetryRepository,
)
from supplier.execution.fake_adapter import (  # noqa: E402
    FakeInventoryMutationAdapter,
)


DEMO_SKU = "REENTRY-DEMO-SKU"
DEMO_VARIANT = (
    "gid://shopify/ProductVariant/930001"
)


def digest(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Demonstrate acknowledged DLQ resolution and one controlled "
            "fake re-entry attempt."
        )
    )

    parser.add_argument(
        "--approve-fingerprint",
        default=None,
    )

    parser.add_argument(
        "--simulate-failure",
        action="store_true",
    )

    return parser.parse_args()


def ensure_demo_case():
    retry_id = digest(
        "v2.6f-demo-retry"
    )

    retry_repository = (
        SupplierBatchRetryRepository()
    )

    retry_repository.append(
        RetryAuditEvent(
            retry_id=retry_id,
            source_batch_id=digest(
                "v2.6f-demo-batch"
            ),
            item_index=1,
            operation_id=digest(
                "v2.6f-demo-operation"
            ),
            shopify_variant_id=(
                DEMO_VARIANT
            ),
            shopify_sku=(
                DEMO_SKU
            ),
            before_quantity=3,
            requested_quantity=14,
            inventory_delta=11,
            attempt_number=3,
            event_type=(
                RetryEventType
                .RETRY_EXHAUSTED
            ),
        )
    )

    dlq_repository = (
        SupplierDeadLetterRepository()
    )

    dlq_service = (
        SupplierDeadLetterService(
            dlq_repository
        )
    )

    dlq_service.scan_and_open_cases()

    case = next(
        item
        for item in dlq_repository.get_cases(
            limit=100
        )
        if item.shopify_sku
        == DEMO_SKU
    )

    if case.status != "acknowledged":
        dlq_service.acknowledge_case(
            case_id=(
                case.case_id
            ),
            actor="Thomas",
            note=(
                "V2.6F controlled re-entry demo investigation."
            ),
        )

    return case.case_id


def main() -> int:
    args = parse_args()

    case_id = ensure_demo_case()

    repository = (
        SupplierCaseResolutionRepository()
    )

    service = (
        SupplierCaseResolutionService(
            repository
        )
    )

    resolution = service.record_resolution(
        case_id=case_id,
        resolution_code=(
            ResolutionCode.SUPPLIER_FIXED
        ),
        actor="Thomas",
        note=(
            "Supplier issue reviewed and corrected; "
            "one isolated recovery attempt is approved for review."
        ),
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.6 CASE RESOLUTION + CONTROLLED RE-ENTRY"
    )
    print("=" * 72)
    print(
        "MODE: SYNTHETIC / NON-LIVE"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )
    print("-" * 72)
    print(
        f"Case ID:"
    )
    print(
        resolution.case_id
    )
    print(
        f"Shopify SKU: "
        f"{resolution.shopify_sku}"
    )
    print(
        f"Requested recovery quantity: "
        f"{resolution.requested_quantity}"
    )
    print(
        f"Resolution code: "
        f"{resolution.resolution_code.value.upper()}"
    )
    print(
        f"Resolution actor: "
        f"{resolution.actor}"
    )
    print(
        "Resolution fingerprint:"
    )
    print(
        resolution.resolution_fingerprint
    )
    print("-" * 72)

    if args.approve_fingerprint is None:
        print(
            "RE-ENTRY STATUS: APPROVAL_REQUIRED"
        )
        print(
            "FAKE RECOVERY ATTEMPTS: 0"
        )
        print(
            "CASE CLOSED: False"
        )
        print()
        print(
            "Re-run with:"
        )
        print(
            "python scripts/"
            "supplier_case_resolution_demo.py "
            "--approve-fingerprint "
            f"{resolution.resolution_fingerprint}"
        )
        return 0

    adapter = (
        FakeInventoryMutationAdapter(
            fail_variant_ids=(
                {DEMO_VARIANT}
                if args.simulate_failure
                else set()
            )
        )
    )

    try:
        result = service.execute_reentry(
            case_id=case_id,
            approved_resolution_fingerprint=(
                args.approve_fingerprint
            ),
            inventory_port=adapter,
        )
    except CaseResolutionError as exc:
        print(
            "RE-ENTRY STATUS: BLOCKED"
        )
        print(
            f"Reason: {exc}"
        )
        return 1

    print(
        "RE-ENTRY STATUS: "
        + (
            "SUCCEEDED"
            if result.applied
            else "FAILED"
        )
    )
    print(
        f"FAKE RECOVERY ATTEMPTS: "
        f"{len(adapter.mutations)}"
    )

    for mutation in adapter.mutations:
        print(
            f"  {mutation.shopify_sku} "
            f"-> {mutation.inventory_quantity}"
        )

    print(
        f"CASE CLOSED: "
        f"{result.closed}"
    )
    print(
        f"Resolution ledger events stored: "
        f"{repository.count_events()}"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )
    print(
        "SQLITE AUDIT WRITES: ENABLED"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
