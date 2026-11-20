from __future__ import annotations

from dataclasses import dataclass

from supplier.batch.case_resolution_models import (
    ResolutionCode,
)


class OperatorWorkflowError(ValueError):
    """Raised when an operator workflow cannot be prepared or executed safely."""


@dataclass(frozen=True)
class OperatorCasePlan:
    case_id: str
    shopify_sku: str
    shopify_variant_id: str
    requested_quantity: int

    dead_letter_status: str
    dead_letter_reason: str

    needs_acknowledgement: bool


@dataclass(frozen=True)
class OperatorWorkflowPlan:
    actor: str
    acknowledgement_note: str
    resolution_note: str
    resolution_code: ResolutionCode

    cases: tuple[OperatorCasePlan, ...]

    workflow_fingerprint: str

    @property
    def case_count(self) -> int:
        return len(self.cases)


@dataclass(frozen=True)
class OperatorCaseExecutionResult:
    case_id: str
    shopify_sku: str

    acknowledged_now: bool
    resolution_fingerprint: str

    recovery_attempted: bool
    recovery_applied: bool
    case_closed: bool


@dataclass(frozen=True)
class OperatorWorkflowExecutionResult:
    workflow_fingerprint: str

    cases_seen: int
    cases_closed: int
    acknowledgements_written: int
    fake_recovery_attempts: int
    fake_recovery_successes: int

    case_results: tuple[
        OperatorCaseExecutionResult,
        ...
    ]

    @property
    def succeeded(self) -> bool:
        return (
            self.cases_seen > 0
            and self.cases_closed
            == self.cases_seen
        )
