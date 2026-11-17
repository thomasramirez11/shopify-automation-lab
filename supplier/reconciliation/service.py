from __future__ import annotations

from supplier.reconciliation.models import (
    ReconciliationObservation,
    ReconciliationRunSummary,
    ReconciliationStatus,
)
from supplier.reconciliation.repository import (
    SupplierExecutionReconciliationRepository,
)


class SupplierExecutionReconciliationService:
    """
    Reconcile V2 verified writes against a later successful V1 sync.
    """

    def __init__(
        self,
        repository: SupplierExecutionReconciliationRepository,
    ) -> None:
        self._repository = repository

    def reconcile_all(
        self,
    ) -> ReconciliationRunSummary:
        candidates = (
            self._repository
            .get_verified_execution_candidates()
        )

        already_matched = 0
        waiting = 0
        written = 0
        matches = 0
        mismatches = 0
        missing = 0

        for candidate in candidates:
            if self._repository.has_match(
                candidate.operation_id
            ):
                already_matched += 1
                continue

            sync_run = (
                self._repository
                .latest_successful_sync_after(
                    candidate.baseline_sync_run_id
                )
            )

            if sync_run is None:
                waiting += 1
                continue

            variant = (
                self._repository
                .get_variant_inventory(
                    candidate.shopify_variant_id
                )
            )

            if variant is None:
                status = (
                    ReconciliationStatus
                    .VARIANT_MISSING
                )
                observed = None
                missing += 1

            else:
                observed = (
                    variant[
                        "inventory_quantity"
                    ]
                )

                if (
                    observed
                    == candidate.expected_quantity
                ):
                    status = (
                        ReconciliationStatus.MATCH
                    )
                    matches += 1
                else:
                    status = (
                        ReconciliationStatus.MISMATCH
                    )
                    mismatches += 1

            result = self._repository.append(
                ReconciliationObservation(
                    operation_id=(
                        candidate.operation_id
                    ),
                    verified_event_id=(
                        candidate.verified_event_id
                    ),
                    sync_run_id=(
                        sync_run["id"]
                    ),
                    shopify_variant_id=(
                        candidate.shopify_variant_id
                    ),
                    shopify_sku=(
                        candidate.shopify_sku
                    ),
                    expected_quantity=(
                        candidate.expected_quantity
                    ),
                    observed_sqlite_quantity=(
                        observed
                    ),
                    status=status,
                )
            )

            if result.created_new:
                written += 1

        return ReconciliationRunSummary(
            verified_operations_seen=(
                len(candidates)
            ),
            already_matched=(
                already_matched
            ),
            waiting_for_new_v1_sync=(
                waiting
            ),
            reconciliations_written=(
                written
            ),
            matches_written=(
                matches
            ),
            mismatches_written=(
                mismatches
            ),
            missing_variants_written=(
                missing
            ),
        )
