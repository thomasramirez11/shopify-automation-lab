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


from supplier.batch.dead_letter_repository import (  # noqa: E402
    SupplierDeadLetterRepository,
)


def main() -> int:
    repository = (
        SupplierDeadLetterRepository()
    )

    repository.ensure_schema()

    cases = repository.get_cases(
        limit=20
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.6 DEAD-LETTER QUEUE"
    )
    print("=" * 72)
    print(
        "LEDGER MODE: APPEND ONLY"
    )
    print(
        f"Cases: {len(cases)}"
    )
    print(
        f"Events: {repository.count_events()}"
    )
    print("-" * 72)

    if not cases:
        print(
            "No dead-letter cases."
        )
        return 0

    for case in cases:
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

        if case.acknowledged_by:
            print(
                f"Human owner: "
                f"{case.acknowledged_by}"
            )
            print(
                f"Note: "
                f"{case.acknowledgement_note}"
            )

        print(
            "Automatic retry allowed: False"
        )
        print("-" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
