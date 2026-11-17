from __future__ import annotations

from supplier.batch.case_resolution_models import (
    CaseResolutionError,
    CaseResolutionEvent,
    ReentryExecutionResult,
    ResolutionCode,
    ResolutionEventType,
    ResolutionRecord,
)
from supplier.batch.case_resolution_policy import (
    build_resolution_fingerprint,
)
from supplier.batch.case_resolution_repository import (
    SupplierCaseResolutionRepository,
)
from supplier.execution.models import (
    InventoryMutation,
)
from supplier.execution.ports import (
    InventoryMutationPort,
)


class SupplierCaseResolutionService:
    """
    Human resolution -> exact approval -> one isolated re-entry attempt.

    No automatic retry owns a dead-letter case after escalation.
    """

    def __init__(
        self,
        repository: SupplierCaseResolutionRepository,
    ) -> None:
        self._repository = repository

    def record_resolution(
        self,
        *,
        case_id: str,
        resolution_code: ResolutionCode,
        actor: str,
        note: str,
    ) -> ResolutionRecord:
        case = (
            self._repository
            .get_acknowledged_case(
                case_id
            )
        )

        if case is None:
            raise CaseResolutionError(
                "Dead-letter case must be acknowledged before resolution."
            )

        fingerprint = (
            build_resolution_fingerprint(
                case=case,
                resolution_code=(
                    resolution_code
                ),
                actor=actor,
                note=note,
            )
        )

        existing = (
            self._repository
            .get_event(
                case_id=case_id,
                event_type=(
                    ResolutionEventType
                    .RESOLUTION_RECORDED
                    .value
                ),
            )
        )

        if existing is not None:
            if (
                existing.resolution_fingerprint
                != fingerprint
            ):
                raise CaseResolutionError(
                    "Case already has a different recorded resolution."
                )

            return ResolutionRecord(
                case_id=(
                    existing.case_id
                ),
                resolution_fingerprint=(
                    existing
                    .resolution_fingerprint
                ),
                resolution_code=(
                    ResolutionCode(
                        existing.resolution_code
                    )
                ),
                actor=(
                    existing.actor
                ),
                note=(
                    existing.note
                ),
                shopify_variant_id=(
                    existing
                    .shopify_variant_id
                ),
                shopify_sku=(
                    existing.shopify_sku
                ),
                requested_quantity=(
                    existing
                    .requested_quantity
                ),
            )

        self._repository.append(
            CaseResolutionEvent(
                case_id=(
                    case.case_id
                ),
                resolution_fingerprint=(
                    fingerprint
                ),
                event_type=(
                    ResolutionEventType
                    .RESOLUTION_RECORDED
                ),
                resolution_code=(
                    resolution_code
                ),
                actor=actor,
                note=note,
                shopify_variant_id=(
                    case.shopify_variant_id
                ),
                shopify_sku=(
                    case.shopify_sku
                ),
                requested_quantity=(
                    case.requested_quantity
                ),
            )
        )

        return ResolutionRecord(
            case_id=(
                case.case_id
            ),
            resolution_fingerprint=(
                fingerprint
            ),
            resolution_code=(
                resolution_code
            ),
            actor=actor,
            note=note,
            shopify_variant_id=(
                case.shopify_variant_id
            ),
            shopify_sku=(
                case.shopify_sku
            ),
            requested_quantity=(
                case.requested_quantity
            ),
        )

    def authorize_reentry(
        self,
        *,
        case_id: str,
        approved_resolution_fingerprint: str,
    ):
        recorded = (
            self._repository
            .get_event(
                case_id=case_id,
                event_type=(
                    ResolutionEventType
                    .RESOLUTION_RECORDED
                    .value
                ),
            )
        )

        if recorded is None:
            raise CaseResolutionError(
                "Resolution must be recorded before re-entry authorization."
            )

        approved = (
            approved_resolution_fingerprint
            .strip()
            .lower()
        )

        if (
            approved
            != recorded
            .resolution_fingerprint
        ):
            raise CaseResolutionError(
                "Approved resolution fingerprint does not match."
            )

        existing_outcome = self._get_outcome(
            case_id
        )

        if existing_outcome is not None:
            raise CaseResolutionError(
                "Re-entry already has a terminal outcome."
            )

        existing = (
            self._repository
            .get_event(
                case_id=case_id,
                event_type=(
                    ResolutionEventType
                    .REENTRY_AUTHORIZED
                    .value
                ),
            )
        )

        if existing is not None:
            return existing

        result = self._repository.append(
            self._copy_event(
                source=recorded,
                event_type=(
                    ResolutionEventType
                    .REENTRY_AUTHORIZED
                ),
            )
        )

        return self._event_by_id(
            case_id=case_id,
            event_id=(
                result.resolution_event_id
            ),
        )

    def execute_reentry(
        self,
        *,
        case_id: str,
        approved_resolution_fingerprint: str,
        inventory_port: InventoryMutationPort,
    ) -> ReentryExecutionResult:
        authorized = (
            self.authorize_reentry(
                case_id=case_id,
                approved_resolution_fingerprint=(
                    approved_resolution_fingerprint
                ),
            )
        )

        existing_outcome = self._get_outcome(
            case_id
        )

        if existing_outcome is not None:
            raise CaseResolutionError(
                "Re-entry already has a terminal outcome."
            )

        self._repository.append(
            self._copy_event(
                source=authorized,
                event_type=(
                    ResolutionEventType
                    .REENTRY_STARTED
                ),
            )
        )

        mutation = InventoryMutation(
            shopify_variant_id=(
                authorized.shopify_variant_id
            ),
            shopify_sku=(
                authorized.shopify_sku
            ),
            inventory_quantity=(
                authorized.requested_quantity
            ),
        )

        result = (
            inventory_port
            .set_inventory(
                mutation
            )
        )

        if result.applied:
            self._repository.append(
                self._copy_event(
                    source=authorized,
                    event_type=(
                        ResolutionEventType
                        .REENTRY_SUCCEEDED
                    ),
                )
            )

            self._repository.append(
                self._copy_event(
                    source=authorized,
                    event_type=(
                        ResolutionEventType
                        .CASE_CLOSED
                    ),
                )
            )

            return ReentryExecutionResult(
                case_id=case_id,
                resolution_fingerprint=(
                    authorized
                    .resolution_fingerprint
                ),
                attempted=True,
                applied=True,
                closed=True,
                shopify_sku=(
                    authorized.shopify_sku
                ),
                requested_quantity=(
                    authorized
                    .requested_quantity
                ),
            )

        self._repository.append(
            self._copy_event(
                source=authorized,
                event_type=(
                    ResolutionEventType
                    .REENTRY_FAILED
                ),
                error_message=(
                    "Controlled re-entry mutation adapter "
                    "reported applied=False."
                ),
            )
        )

        return ReentryExecutionResult(
            case_id=case_id,
            resolution_fingerprint=(
                authorized
                .resolution_fingerprint
            ),
            attempted=True,
            applied=False,
            closed=False,
            shopify_sku=(
                authorized.shopify_sku
            ),
            requested_quantity=(
                authorized
                .requested_quantity
            ),
        )

    def _get_outcome(
        self,
        case_id: str,
    ):
        succeeded = (
            self._repository
            .get_event(
                case_id=case_id,
                event_type=(
                    ResolutionEventType
                    .REENTRY_SUCCEEDED
                    .value
                ),
            )
        )

        if succeeded is not None:
            return succeeded

        return (
            self._repository
            .get_event(
                case_id=case_id,
                event_type=(
                    ResolutionEventType
                    .REENTRY_FAILED
                    .value
                ),
            )
        )

    def _copy_event(
        self,
        *,
        source,
        event_type: ResolutionEventType,
        error_message: str | None = None,
    ) -> CaseResolutionEvent:
        return CaseResolutionEvent(
            case_id=(
                source.case_id
            ),
            resolution_fingerprint=(
                source.resolution_fingerprint
            ),
            event_type=(
                event_type
            ),
            resolution_code=(
                ResolutionCode(
                    source.resolution_code
                )
            ),
            actor=(
                source.actor
            ),
            note=(
                source.note
            ),
            shopify_variant_id=(
                source.shopify_variant_id
            ),
            shopify_sku=(
                source.shopify_sku
            ),
            requested_quantity=(
                source.requested_quantity
            ),
            error_message=(
                error_message
            ),
        )

    def _event_by_id(
        self,
        *,
        case_id: str,
        event_id: int,
    ):
        for event in (
            self._repository
            .get_events(
                case_id
            )
        ):
            if (
                event.resolution_event_id
                == event_id
            ):
                return event

        raise RuntimeError(
            "Resolution event could not be read after append."
        )
