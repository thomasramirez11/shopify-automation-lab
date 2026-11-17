from __future__ import annotations

import string
from dataclasses import dataclass
from enum import Enum

from supplier.batch.models import (
    BatchSafetyManifest,
    BatchSafetyStatus,
)
from supplier.plan.models import (
    SupplierSyncPlan,
)


class BatchApprovalStatus(str, Enum):
    READY = "ready"
    BATCH_NOT_READY = "batch_not_ready"
    SOURCE_PLAN_MISMATCH = "source_plan_mismatch"
    APPROVAL_REQUIRED = "approval_required"
    MANIFEST_FINGERPRINT_MISMATCH = (
        "manifest_fingerprint_mismatch"
    )


@dataclass(frozen=True)
class BatchApprovalReport:
    status: BatchApprovalStatus

    current_manifest_fingerprint: str
    approved_manifest_fingerprint: str | None

    source_plan_fingerprint: str
    current_plan_fingerprint: str

    planned_mutations: int
    total_absolute_inventory_delta: int

    @property
    def can_execute(
        self,
    ) -> bool:
        return (
            self.status
            == BatchApprovalStatus.READY
        )


def evaluate_batch_approval(
    *,
    plan: SupplierSyncPlan,
    manifest: BatchSafetyManifest,
    approved_manifest_fingerprint: str | None,
) -> BatchApprovalReport:
    """
    Final batch-level approval gate.

    The human approves the manifest fingerprint, not only the plan
    fingerprint. The manifest fingerprint includes:
    - source plan fingerprint
    - mutation contents
    - blast-radius policy
    - batch safety result

    Therefore a changed plan OR changed safety policy invalidates approval.
    """

    normalized_approval = (
        _normalize_fingerprint(
            approved_manifest_fingerprint
        )
    )

    if (
        manifest.status
        != BatchSafetyStatus.READY
    ):
        status = (
            BatchApprovalStatus
            .BATCH_NOT_READY
        )

    elif (
        manifest.source_plan_fingerprint
        != plan.fingerprint
    ):
        status = (
            BatchApprovalStatus
            .SOURCE_PLAN_MISMATCH
        )

    elif normalized_approval is None:
        status = (
            BatchApprovalStatus
            .APPROVAL_REQUIRED
        )

    elif (
        normalized_approval
        != manifest.manifest_fingerprint
    ):
        status = (
            BatchApprovalStatus
            .MANIFEST_FINGERPRINT_MISMATCH
        )

    else:
        status = (
            BatchApprovalStatus.READY
        )

    return BatchApprovalReport(
        status=status,
        current_manifest_fingerprint=(
            manifest.manifest_fingerprint
        ),
        approved_manifest_fingerprint=(
            normalized_approval
        ),
        source_plan_fingerprint=(
            manifest.source_plan_fingerprint
        ),
        current_plan_fingerprint=(
            plan.fingerprint
        ),
        planned_mutations=(
            manifest.planned_mutations
        ),
        total_absolute_inventory_delta=(
            manifest
            .total_absolute_inventory_delta
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
