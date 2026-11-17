from __future__ import annotations

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


def digest(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


def main() -> int:
    """
    Seed two synthetic terminal retry cases:
    - one retry exhausted
    - one non-retryable / skipped

    Then promote them into the human dead-letter queue.
    """

    retry_repository = (
        SupplierBatchRetryRepository()
    )

    synthetic_events = [
        RetryAuditEvent(
            retry_id=digest(
                "dlq-demo-exhausted-retry"
            ),
            source_batch_id=digest(
                "dlq-demo-batch-a"
            ),
            item_index=1,
            operation_id=digest(
                "dlq-demo-operation-a"
            ),
            shopify_variant_id=(
                "gid://shopify/ProductVariant/920001"
            ),
            shopify_sku="DLQ-DEMO-EXHAUSTED",
            before_quantity=4,
            requested_quantity=9,
            inventory_delta=5,
            attempt_number=3,
            event_type=(
                RetryEventType
                .RETRY_EXHAUSTED
            ),
        ),
        RetryAuditEvent(
            retry_id=digest(
                "dlq-demo-non-retryable"
            ),
            source_batch_id=digest(
                "dlq-demo-batch-b"
            ),
            item_index=1,
            operation_id=digest(
                "dlq-demo-operation-b"
            ),
            shopify_variant_id=(
                "gid://shopify/ProductVariant/920002"
            ),
            shopify_sku="DLQ-DEMO-NONRETRYABLE",
            before_quantity=6,
            requested_quantity=12,
            inventory_delta=6,
            attempt_number=1,
            event_type=(
                RetryEventType
                .RETRY_SKIPPED
            ),
            error_message=(
                "Synthetic non-retryable failure for DLQ demo."
            ),
        ),
    ]

    for event in synthetic_events:
        retry_repository.append(
            event
        )

    repository = (
        SupplierDeadLetterRepository()
    )
    service = (
        SupplierDeadLetterService(
            repository
        )
    )

    summary = (
        service.scan_and_open_cases()
    )

    cases = repository.get_cases(
        limit=20
    )

    demo_cases = [
        case
        for case in cases
        if case.shopify_sku.startswith(
            "DLQ-DEMO-"
        )
    ]

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.6 DEAD-LETTER + HUMAN ESCALATION DEMO"
    )
    print("=" * 72)
    print(
        "MODE: SYNTHETIC / NON-LIVE"
    )
    print(
        "AUTOMATIC RETRY OWNERSHIP: SURRENDERED"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )
    print("-" * 72)

    print(
        "ESCALATION SCAN"
    )
    print("-" * 72)
    print(
        "Terminal retry candidates seen: "
        f"{summary.escalation_candidates_seen}"
    )
    print(
        f"Cases opened now: "
        f"{summary.cases_opened}"
    )
    print(
        f"Cases already open: "
        f"{summary.already_open}"
    )
    print("-" * 72)

    print(
        "DEMO DEAD-LETTER CASES"
    )
    print("-" * 72)

    for case in demo_cases:
        print(
            f"Case ID:"
        )
        print(
            case.case_id
        )
        print(
            f"Shopify SKU: "
            f"{case.shopify_sku}"
        )
        print(
            f"Requested quantity: "
            f"{case.requested_quantity}"
        )
        print(
            f"Reason: "
            f"{case.reason_code.upper()}"
        )
        print(
            f"Status: "
            f"{case.status.upper()}"
        )
        print(
            "Automation may retry automatically: False"
        )
        print("-" * 72)

    print(
        f"Dead-letter ledger events stored: "
        f"{repository.count_events()}"
    )
    print(
        "SQLITE AUDIT WRITES: ENABLED"
    )

    if demo_cases:
        first = demo_cases[-1]
        print()
        print(
            "NEXT HUMAN ACTION EXAMPLE"
        )
        print(
            "python scripts/"
            "supplier_dead_letter_acknowledge.py "
            f"--case-id {first.case_id} "
            '--actor Thomas '
            '--note "Investigating supplier failure"'
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
