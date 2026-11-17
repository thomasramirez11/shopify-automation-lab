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


from supplier.batch.case_resolution_repository import (  # noqa: E402
    SupplierCaseResolutionRepository,
)


def main() -> int:
    repository = (
        SupplierCaseResolutionRepository()
    )

    repository.ensure_schema()

    cases = repository.get_cases(
        limit=20
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.6 CASE RESOLUTION LEDGER"
    )
    print("=" * 72)
    print(
        "LEDGER MODE: APPEND ONLY"
    )
    print(
        f"Resolution cases: "
        f"{len(cases)}"
    )
    print(
        f"Resolution events: "
        f"{repository.count_events()}"
    )
    print("-" * 72)

    if not cases:
        print(
            "No resolved dead-letter cases yet."
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
            f"Resolution: "
            f"{case.resolution_code.upper()}"
        )
        print(
            f"Status: "
            f"{case.status.upper()}"
        )
        print(
            f"Actor: "
            f"{case.actor}"
        )

        if case.error_message:
            print(
                f"Error: "
                f"{case.error_message}"
            )

        print(
            "Fingerprint:"
        )
        print(
            case.resolution_fingerprint
        )
        print("-" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
