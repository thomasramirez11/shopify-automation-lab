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


from supplier.batch.dead_letter_models import (  # noqa: E402
    DeadLetterError,
)
from supplier.batch.dead_letter_repository import (  # noqa: E402
    SupplierDeadLetterRepository,
)
from supplier.batch.dead_letter_service import (  # noqa: E402
    SupplierDeadLetterService,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Acknowledge ownership of one dead-letter case."
        )
    )

    parser.add_argument(
        "--case-id",
        required=True,
    )
    parser.add_argument(
        "--actor",
        required=True,
    )
    parser.add_argument(
        "--note",
        required=True,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    service = (
        SupplierDeadLetterService(
            SupplierDeadLetterRepository()
        )
    )

    try:
        event = service.acknowledge_case(
            case_id=args.case_id,
            actor=args.actor,
            note=args.note,
        )
    except DeadLetterError as exc:
        print(
            "ACKNOWLEDGEMENT STATUS: BLOCKED"
        )
        print(
            f"Reason: {exc}"
        )
        return 1

    print(
        "SHOPIFY AUTOMATION LAB — "
        "DEAD-LETTER HUMAN ACKNOWLEDGEMENT"
    )
    print("=" * 72)
    print(
        "ACKNOWLEDGEMENT STATUS: RECORDED"
    )
    print(
        f"Case ID: "
        f"{event.case_id}"
    )
    print(
        f"Shopify SKU: "
        f"{event.shopify_sku}"
    )
    print(
        f"Actor: "
        f"{event.actor}"
    )
    print(
        f"Note: "
        f"{event.note}"
    )
    print(
        "AUTOMATIC RETRY OWNERSHIP: SURRENDERED"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
