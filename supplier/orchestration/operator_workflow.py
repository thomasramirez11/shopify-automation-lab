from __future__ import annotations

import hashlib
import json

from supplier.batch.case_resolution_models import (
    ResolutionCode,
)
from supplier.orchestration.operator_models import (
    OperatorCaseExecutionResult,
    OperatorWorkflowError,
    OperatorWorkflowExecutionResult,
    OperatorWorkflowPlan,
    OperatorCasePlan,
)


class SupplierOperatorWorkflow:
    """
    Human-controlled cleanup workflow for unresolved dead-letter cases.

    V2.7C intentionally supports only synthetic DLQ-DEMO-* cases. This gives
    us a real control-plane state transition without risking a live supplier
    or Shopify operation.
    """

    def __init__(
        self,
        *,
        dead_letter_repository,
        dead_letter_service,
        resolution_repository,
        resolution_service,
        allowed_sku_prefix: str = "DLQ-DEMO-",
    ) -> None:
        if (
            not isinstance(
                allowed_sku_prefix,
                str,
            )
            or not allowed_sku_prefix
        ):
            raise OperatorWorkflowError(
                "allowed_sku_prefix must be a non-empty string."
            )

        self._dead_letter_repository = (
            dead_letter_repository
        )
        self._dead_letter_service = (
            dead_letter_service
        )
        self._resolution_repository = (
            resolution_repository
        )
        self._resolution_service = (
            resolution_service
        )
        self._allowed_sku_prefix = (
            allowed_sku_prefix
        )

    def prepare(
        self,
        *,
        actor: str,
        acknowledgement_note: str,
        resolution_note: str,
        resolution_code: ResolutionCode = (
            ResolutionCode.OTHER
        ),
    ) -> OperatorWorkflowPlan:
        _require_text(
            "actor",
            actor,
        )
        _require_text(
            "acknowledgement_note",
            acknowledgement_note,
        )
        _require_text(
            "resolution_note",
            resolution_note,
        )

        cases = []

        for case in (
            self._dead_letter_repository
            .get_cases(
                limit=100
            )
        ):
            if not case.shopify_sku.startswith(
                self._allowed_sku_prefix
            ):
                continue

            closed = (
                self._resolution_repository
                .get_event(
                    case_id=(
                        case.case_id
                    ),
                    event_type="case_closed",
                )
            )

            if closed is not None:
                continue

            terminal_failure = (
                self._resolution_repository
                .get_event(
                    case_id=(
                        case.case_id
                    ),
                    event_type="reentry_failed",
                )
            )

            if terminal_failure is not None:
                raise OperatorWorkflowError(
                    "A synthetic case already has a failed controlled "
                    "re-entry outcome and requires a new remediation design."
                )

            cases.append(
                OperatorCasePlan(
                    case_id=(
                        case.case_id
                    ),
                    shopify_sku=(
                        case.shopify_sku
                    ),
                    shopify_variant_id=(
                        case.shopify_variant_id
                    ),
                    requested_quantity=(
                        case.requested_quantity
                    ),
                    dead_letter_status=(
                        case.status
                    ),
                    dead_letter_reason=(
                        case.reason_code
                    ),
                    needs_acknowledgement=(
                        case.status
                        == "awaiting_human"
                    ),
                )
            )

        ordered_cases = tuple(
            sorted(
                cases,
                key=lambda item: (
                    item.shopify_sku,
                    item.case_id,
                ),
            )
        )

        fingerprint = (
            _build_workflow_fingerprint(
                actor=actor,
                acknowledgement_note=(
                    acknowledgement_note
                ),
                resolution_note=(
                    resolution_note
                ),
                resolution_code=(
                    resolution_code
                ),
                cases=ordered_cases,
                allowed_sku_prefix=(
                    self._allowed_sku_prefix
                ),
            )
        )

        return OperatorWorkflowPlan(
            actor=actor,
            acknowledgement_note=(
                acknowledgement_note
            ),
            resolution_note=(
                resolution_note
            ),
            resolution_code=(
                resolution_code
            ),
            cases=ordered_cases,
            workflow_fingerprint=(
                fingerprint
            ),
        )

    def execute(
        self,
        *,
        plan: OperatorWorkflowPlan,
        approved_workflow_fingerprint: str,
        inventory_port,
    ) -> OperatorWorkflowExecutionResult:
        approved = (
            approved_workflow_fingerprint
            .strip()
            .lower()
        )

        if (
            approved
            != plan.workflow_fingerprint
        ):
            raise OperatorWorkflowError(
                "Approved workflow fingerprint does not match."
            )

        if not plan.cases:
            raise OperatorWorkflowError(
                "Operator workflow contains no unresolved synthetic cases."
            )

        current_plan = self.prepare(
            actor=plan.actor,
            acknowledgement_note=(
                plan.acknowledgement_note
            ),
            resolution_note=(
                plan.resolution_note
            ),
            resolution_code=(
                plan.resolution_code
            ),
        )

        if (
            current_plan.workflow_fingerprint
            != plan.workflow_fingerprint
        ):
            raise OperatorWorkflowError(
                "Operator workflow became stale before execution."
            )

        case_results = []

        acknowledgements_written = 0
        fake_attempts = 0
        fake_successes = 0
        cases_closed = 0

        for case in current_plan.cases:
            acknowledgement_written = False

            if case.needs_acknowledgement:
                self._dead_letter_service.acknowledge_case(
                    case_id=(
                        case.case_id
                    ),
                    actor=plan.actor,
                    note=(
                        plan.acknowledgement_note
                    ),
                )

                acknowledgement_written = True
                acknowledgements_written += 1

            resolution = (
                self._resolution_service
                .record_resolution(
                    case_id=(
                        case.case_id
                    ),
                    resolution_code=(
                        plan.resolution_code
                    ),
                    actor=plan.actor,
                    note=(
                        plan.resolution_note
                    ),
                )
            )

            recovery = (
                self._resolution_service
                .execute_reentry(
                    case_id=(
                        case.case_id
                    ),
                    approved_resolution_fingerprint=(
                        resolution
                        .resolution_fingerprint
                    ),
                    inventory_port=(
                        inventory_port
                    ),
                )
            )

            if recovery.attempted:
                fake_attempts += 1

            if recovery.applied:
                fake_successes += 1

            if recovery.closed:
                cases_closed += 1

            case_results.append(
                OperatorCaseExecutionResult(
                    case_id=(
                        case.case_id
                    ),
                    shopify_sku=(
                        case.shopify_sku
                    ),
                    acknowledged_now=(
                        acknowledgement_written
                    ),
                    resolution_fingerprint=(
                        resolution
                        .resolution_fingerprint
                    ),
                    recovery_attempted=(
                        recovery.attempted
                    ),
                    recovery_applied=(
                        recovery.applied
                    ),
                    case_closed=(
                        recovery.closed
                    ),
                )
            )

        return OperatorWorkflowExecutionResult(
            workflow_fingerprint=(
                plan.workflow_fingerprint
            ),
            cases_seen=(
                len(current_plan.cases)
            ),
            cases_closed=(
                cases_closed
            ),
            acknowledgements_written=(
                acknowledgements_written
            ),
            fake_recovery_attempts=(
                fake_attempts
            ),
            fake_recovery_successes=(
                fake_successes
            ),
            case_results=(
                tuple(
                    case_results
                )
            ),
        )


def _build_workflow_fingerprint(
    *,
    actor: str,
    acknowledgement_note: str,
    resolution_note: str,
    resolution_code: ResolutionCode,
    cases: tuple[OperatorCasePlan, ...],
    allowed_sku_prefix: str,
) -> str:
    payload = {
        "workflow":
            "v2.7c_synthetic_dlq_cleanup",
        "actor":
            actor.strip(),
        "acknowledgement_note":
            acknowledgement_note.strip(),
        "resolution_note":
            resolution_note.strip(),
        "resolution_code":
            resolution_code.value,
        "allowed_sku_prefix":
            allowed_sku_prefix,
        "cases": [
            {
                "case_id":
                    case.case_id,
                "shopify_sku":
                    case.shopify_sku,
                "shopify_variant_id":
                    case.shopify_variant_id,
                "requested_quantity":
                    case.requested_quantity,
                "dead_letter_status":
                    case.dead_letter_status,
                "dead_letter_reason":
                    case.dead_letter_reason,
                "needs_acknowledgement":
                    case.needs_acknowledgement,
            }
            for case in cases
        ],
    }

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()


def _require_text(
    field_name: str,
    value,
) -> None:
    if (
        not isinstance(
            value,
            str,
        )
        or not value.strip()
    ):
        raise OperatorWorkflowError(
            f"{field_name} must be a non-empty string."
        )
