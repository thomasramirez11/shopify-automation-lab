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


from supplier.batch.retry_repository import (  # noqa: E402
    SupplierBatchRetryRepository,
)


def main() -> int:
    repository = (
        SupplierBatchRetryRepository()
    )

    repository.ensure_schema()

    retry_ids = (
        repository.get_recent_retry_ids(
            limit=10
        )
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.6 RETRY LEDGER"
    )
    print("=" * 72)
    print(
        "LEDGER MODE: APPEND ONLY"
    )
    print(
        f"Retry events stored: "
        f"{repository.count_events()}"
    )
    print("-" * 72)

    if not retry_ids:
        print(
            "No retry events stored yet."
        )
        return 0

    for retry_id in retry_ids:
        events = (
            repository.get_retry_events(
                retry_id
            )
        )

        print(
            "RETRY"
        )
        print(
            retry_id
        )

        for event in events:
            suffix = (
                f" | error={event.error_message}"
                if event.error_message
                else ""
            )

            print(
                f"  attempt={event.attempt_number} "
                f"{event.event_type.upper()} | "
                f"{event.shopify_sku} "
                f"{event.before_quantity} -> "
                f"{event.requested_quantity}"
                f"{suffix}"
            )

        print("-" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
