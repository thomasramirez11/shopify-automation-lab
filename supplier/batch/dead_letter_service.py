from __future__ import annotations

from supplier.batch.dead_letter_models import (
    DeadLetterAuditEvent,
    DeadLetterError,
    DeadLetterEventType,
    DeadLetterScanSummary,
)
from supplier.batch.dead_letter_policy import (
    build_dead_letter_case_id,
)
from supplier.batch.dead_letter_repository import (
    SupplierDeadLetterRepository,
)


class SupplierDeadLetterService:
    """
    Transfer ownership from automation to a human-review queue.
    """

    def __init__(
        self,
        repository: SupplierDeadLetterRepository,
    ) -> None:
        self._repository = repository

    def scan_and_open_cases(
        self,
    ) -> DeadLetterScanSummary:
        candidates = (
            self._repository
            .discover_escalation_candidates()
        )

        opened = 0
        already_open = 0

        for candidate in candidates:
            case_id = (
                build_dead_letter_case_id(
                    candidate
                )
            )

            result = (
                self._repository.append(
                    DeadLetterAuditEvent(
                        case_id=case_id,
                        source_retry_id=(
                            candidate
                            .source_retry_id
                        ),
                        source_batch_id=(
                            candidate
                            .source_batch_id
                        ),
                        item_index=(
                            candidate.item_index
                        ),
                        operation_id=(
                            candidate.operation_id
                        ),
                        shopify_variant_id=(
                            candidate
                            .shopify_variant_id
                        ),
                        shopify_sku=(
                            candidate.shopify_sku
                        ),
                        requested_quantity=(
                            candidate
                            .requested_quantity
                        ),
                        reason=(
                            candidate.reason
                        ),
                        event_type=(
                            DeadLetterEventType
                            .CASE_OPENED
                        ),
                    )
                )
            )

            if result.created_new:
                opened += 1
            else:
                already_open += 1

        return DeadLetterScanSummary(
            escalation_candidates_seen=(
                len(candidates)
            ),
            cases_opened=opened,
            already_open=already_open,
        )

    def acknowledge_case(
        self,
        *,
        case_id: str,
        actor: str,
        note: str,
    ):
        opened = (
            self._repository
            .get_opened_event(
                case_id
            )
        )

        if opened is None:
            raise DeadLetterError(
                "Cannot acknowledge an unknown dead-letter case."
            )

        existing = (
            self._repository
            .get_acknowledged_event(
                case_id
            )
        )

        if existing is not None:
            if (
                existing.actor == actor
                and existing.note == note
            ):
                return existing

            raise DeadLetterError(
                "Dead-letter case is already acknowledged with different details."
            )

        result = (
            self._repository.append(
                DeadLetterAuditEvent(
                    case_id=(
                        opened.case_id
                    ),
                    source_retry_id=(
                        opened.source_retry_id
                    ),
                    source_batch_id=(
                        opened.source_batch_id
                    ),
                    item_index=(
                        opened.item_index
                    ),
                    operation_id=(
                        opened.operation_id
                    ),
                    shopify_variant_id=(
                        opened.shopify_variant_id
                    ),
                    shopify_sku=(
                        opened.shopify_sku
                    ),
                    requested_quantity=(
                        opened.requested_quantity
                    ),
                    reason=_reason_from_text(
                        opened.reason_code
                    ),
                    event_type=(
                        DeadLetterEventType
                        .CASE_ACKNOWLEDGED
                    ),
                    actor=actor,
                    note=note,
                )
            )
        )

        events = (
            self._repository
            .get_case_events(
                case_id
            )
        )

        for event in events:
            if (
                event.dead_letter_event_id
                == result.dead_letter_event_id
            ):
                return event

        raise RuntimeError(
            "Acknowledgement could not be read after append."
        )


def _reason_from_text(
    value: str,
):
    from supplier.batch.dead_letter_models import (
        DeadLetterReason,
    )

    return DeadLetterReason(
        value
    )
