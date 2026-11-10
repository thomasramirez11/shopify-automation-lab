from __future__ import annotations

import string

from supplier.guard.models import (
    ExecutionGuardReport,
    ExecutionGuardStatus,
)
from supplier.plan.models import (
    SupplierSyncPlan,
)


def evaluate_execution_guard(
    *,
    plan: SupplierSyncPlan,
    approved_fingerprint: str | None,
) -> ExecutionGuardReport:
    """
    Determine whether the CURRENT dry-run plan is safe to hand to a future
    executor.

    Safety rules:
    1. BLOCKED plan items stop execution.
    2. REVIEW plan items require human intervention.
    3. A plan with no mutations does not need execution.
    4. Explicit approval is required.
    5. Approval must match the exact current plan fingerprint.

    This function performs no writes and no network calls.
    """

    normalized_approval = (
        _normalize_fingerprint(
            approved_fingerprint
        )
    )

    if plan.blocked_items > 0:
        status = (
            ExecutionGuardStatus
            .BLOCKED_ITEMS_PRESENT
        )

    elif plan.review_items > 0:
        status = (
            ExecutionGuardStatus
            .REVIEW_REQUIRED
        )

    elif plan.planned_mutations == 0:
        status = (
            ExecutionGuardStatus
            .NO_MUTATIONS
        )

    elif normalized_approval is None:
        status = (
            ExecutionGuardStatus
            .APPROVAL_REQUIRED
        )

    elif (
        normalized_approval
        != plan.fingerprint
    ):
        status = (
            ExecutionGuardStatus
            .FINGERPRINT_MISMATCH
        )

    else:
        status = (
            ExecutionGuardStatus.READY
        )

    return ExecutionGuardReport(
        status=status,
        current_plan_fingerprint=(
            plan.fingerprint
        ),
        approved_plan_fingerprint=(
            normalized_approval
        ),
        planned_mutations=(
            plan.planned_mutations
        ),
        review_items=(
            plan.review_items
        ),
        blocked_items=(
            plan.blocked_items
        ),
    )


def _normalize_fingerprint(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    normalized = (
        value.strip().lower()
    )

    if not normalized:
        return None

    # Keep malformed approvals deterministic: they simply cannot match a
    # valid SHA-256 plan fingerprint.
    if (
        len(normalized) != 64
        or any(
            character
            not in string.hexdigits
            for character in normalized
        )
    ):
        return normalized

    return normalized
