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


from supplier.batch.case_resolution_models import (  # noqa: E402
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
from supplier.execution.fake_adapter import (  # noqa: E402
    FakeInventoryMutationAdapter,
)
from supplier.orchestration.operator_models import (  # noqa: E402
    OperatorWorkflowError,
)
from supplier.orchestration.operator_workflow import (  # noqa: E402
    SupplierOperatorWorkflow,
)


ACTOR = "Thomas"

ACKNOWLEDGEMENT_NOTE = (
    "V2.7C synthetic DLQ cleanup: operator ownership accepted."
)

RESOLUTION_NOTE = (
    "Synthetic V2.6E validation case reviewed; "
    "controlled fake re-entry approved to clear test operational debt."
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or execute the V2.7C synthetic DLQ operator workflow."
        )
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Execute the exact prepared synthetic workflow using only "
            "the fake inventory adapter."
        ),
    )

    parser.add_argument(
        "--approve-fingerprint",
        default=None,
        help=(
            "Exact workflow fingerprint printed during PREPARE."
        ),
    )

    return parser.parse_args()


def build_workflow():
    dead_letter_repository = (
        SupplierDeadLetterRepository()
    )

    resolution_repository = (
        SupplierCaseResolutionRepository()
    )

    return SupplierOperatorWorkflow(
        dead_letter_repository=(
            dead_letter_repository
        ),
        dead_letter_service=(
            SupplierDeadLetterService(
                dead_letter_repository
            )
        ),
        resolution_repository=(
            resolution_repository
        ),
        resolution_service=(
            SupplierCaseResolutionService(
                resolution_repository
            )
        ),
        allowed_sku_prefix=(
            "DLQ-DEMO-"
        ),
    )


def main() -> int:
    args = parse_args()

    workflow = build_workflow()

    try:
        plan = workflow.prepare(
            actor=ACTOR,
            acknowledgement_note=(
                ACKNOWLEDGEMENT_NOTE
            ),
            resolution_note=(
                RESOLUTION_NOTE
            ),
            resolution_code=(
                ResolutionCode.OTHER
            ),
        )
    except OperatorWorkflowError as exc:
        print(
            "WORKFLOW STATUS: BLOCKED"
        )
        print(
            f"Reason: {exc}"
        )
        return 1

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 OPERATOR WORKFLOW"
    )
    print("=" * 72)
    print(
        "SCOPE: SYNTHETIC DLQ-DEMO-* CASES ONLY"
    )
    print(
        "LIVE SHOPIFY WRITES: DISABLED"
    )
    print("-" * 72)

    print(
        "WORKFLOW PLAN"
    )
    print("-" * 72)
    print(
        f"Cases selected: "
        f"{plan.case_count}"
    )

    if not plan.cases:
        print(
            "No unresolved synthetic DLQ cases remain."
        )
        print(
            "WORKFLOW STATUS: EMPTY"
        )
        print(
            "SHOPIFY WRITES PERFORMED: 0"
        )
        return 0

    for index, case in enumerate(
        plan.cases,
        start=1,
    ):
        print(
            f"Case #{index}"
        )
        print(
            f"  SKU: "
            f"{case.shopify_sku}"
        )
        print(
            f"  DLQ status: "
            f"{case.dead_letter_status.upper()}"
        )
        print(
            f"  Reason: "
            f"{case.dead_letter_reason.upper()}"
        )
        print(
            f"  Requested quantity: "
            f"{case.requested_quantity}"
        )
        print(
            f"  Needs acknowledgement: "
            f"{case.needs_acknowledgement}"
        )

    print("-" * 72)
    print(
        "Workflow fingerprint:"
    )
    print(
        plan.workflow_fingerprint
    )
    print("-" * 72)

    if not args.apply:
        print(
            "WORKFLOW STATUS: APPROVAL_REQUIRED"
        )
        print(
            "SQLITE AUDIT WRITES: 0"
        )
        print(
            "FAKE RECOVERY ATTEMPTS: 0"
        )
        print()
        print(
            "Re-run with:"
        )
        print(
            "python scripts/"
            "supplier_operator_workflow.py "
            "--apply "
            "--approve-fingerprint "
            f"{plan.workflow_fingerprint}"
        )
        return 0

    if args.approve_fingerprint is None:
        print(
            "WORKFLOW STATUS: BLOCKED"
        )
        print(
            "Reason: --approve-fingerprint is required with --apply."
        )
        return 1

    adapter = (
        FakeInventoryMutationAdapter()
    )

    try:
        result = workflow.execute(
            plan=plan,
            approved_workflow_fingerprint=(
                args.approve_fingerprint
            ),
            inventory_port=adapter,
        )
    except OperatorWorkflowError as exc:
        print(
            "WORKFLOW STATUS: BLOCKED"
        )
        print(
            f"Reason: {exc}"
        )
        return 1

    print(
        "WORKFLOW EXECUTION"
    )
    print("-" * 72)
    print(
        f"Cases processed: "
        f"{result.cases_seen}"
    )
    print(
        f"Cases closed: "
        f"{result.cases_closed}"
    )
    print(
        f"Acknowledgements written: "
        f"{result.acknowledgements_written}"
    )
    print(
        f"Fake recovery attempts: "
        f"{result.fake_recovery_attempts}"
    )
    print(
        f"Fake recovery successes: "
        f"{result.fake_recovery_successes}"
    )

    for case_result in result.case_results:
        print(
            f"  {case_result.shopify_sku} "
            f"| acknowledged_now="
            f"{case_result.acknowledged_now} "
            f"| recovery_applied="
            f"{case_result.recovery_applied} "
            f"| closed="
            f"{case_result.case_closed}"
        )

    print("-" * 72)
    print(
        f"WORKFLOW STATUS: "
        f"{'SUCCEEDED' if result.succeeded else 'INCOMPLETE'}"
    )
    print(
        "LIVE SHOPIFY WRITES: 0"
    )
    print(
        "SQLITE AUDIT WRITES: ENABLED"
    )
    print()
    print(
        "NEXT STEP:"
    )
    print(
        "python scripts/"
        "supplier_operations_control_plane_run.py"
    )

    return (
        0
        if result.succeeded
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
