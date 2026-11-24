"""V2.8B/5 controlled *fake-only* Shopify batch sender.

No HTTP client import, no Shopify credentials, and no live mutation transport.
This checkpoint proves pre-send journaling, response classification and strict
single-attempt semantics with deterministic scripted responses.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from supplier.batch.live_fake_receipt_repository import (
    FakeResponseReceipt, SupplierLiveBatchFakeReceiptRepository,
)
from supplier.batch.live_recovery_models import RecoveryConflict
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService
from supplier.batch.live_response_policy import (
    ResponseAssessment, SimulatedResponseStatus, classify_shopify_response,
)


class ScriptedFakeShopifyTransport:
    """A single predefined return value or simulated exception; never HTTP."""

    def __init__(self, scripted_result: Any) -> None:
        self._result = scripted_result
        self.calls = 0
        self.sent_queries: list[str] = []
        self.sent_variables: list[dict] = []

    def send(self, query: str, variables: dict) -> Any:
        self.calls += 1
        self.sent_queries.append(query)
        self.sent_variables.append(deepcopy(variables))
        if isinstance(self._result, BaseException):
            raise self._result
        return deepcopy(self._result)


@dataclass(frozen=True, slots=True)
class FakeSendResult:
    receipt: FakeResponseReceipt
    assessment: ResponseAssessment
    network_calls: int = 0
    live_shopify_writes: int = 0


class SupplierLiveBatchFakeSender:
    """Composes the real durable recovery journal with an offline fake transport.

    No injection of a custom network client is allowed in V2.8B/5.
    A real sender will require a separate reviewed module/checkpoint.
    """

    def __init__(self, *, recovery_service: SupplierLiveBatchRecoveryService,
                 receipt_repository: SupplierLiveBatchFakeReceiptRepository) -> None:
        if receipt_repository._connection_factory is not recovery_service._recovery._connection_factory:
            raise RecoveryConflict("fake sender and recovery journal must share one SQLite connection factory")
        self._recovery_service = recovery_service
        self._receipt_repository = receipt_repository

    def send_once(self, *, operation_id: str, transport: ScriptedFakeShopifyTransport) -> FakeSendResult:
        if type(transport) is not ScriptedFakeShopifyTransport:
            raise RecoveryConflict("V2.8B/5 accepts ONLY the in-memory scripted fake transport")
        snapshot = self._recovery_service._recovery.load_snapshot(operation_id)
        if self._recovery_service._recovery.events(operation_id):
            raise RecoveryConflict("already dispatched; repeating a fake send is forbidden")
        # This must commit before any possible side effect, even in a fake demo.
        self._recovery_service.arm_dispatch(
            operation_id=operation_id, request_digest=snapshot.request_digest,
        )
        expected_uri = snapshot.payload["variables"]["input"]["referenceDocumentUri"]
        try:
            response = transport.send(
                snapshot.payload["query"], snapshot.payload["variables"],
            )
        except Exception:
            # Never persist exceptions, raw HTTP bodies or credentials.
            assessment = ResponseAssessment(
                SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW,
                "TRANSPORT_EXCEPTION_OUTCOME_UNKNOWN",
            )
            # Recovery journal remains conservative even if note_outcome_unknown
            # cannot be persisted due to a second, independent disk failure.
            self._recovery_service.note_outcome_unknown(operation_id=operation_id)
        else:
            assessment = classify_shopify_response(response, expected_reference_uri=expected_uri)
        receipt = self._receipt_repository.record(
            recovery_repository=self._recovery_service._recovery,
            operation_id=operation_id,
            assessment=assessment,
        )
        return FakeSendResult(receipt, assessment)
