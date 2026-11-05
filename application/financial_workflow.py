from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from application.presentation_ports import (
    SyncWorkflowPresenter,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinancialWorkflowResult:
    """
    Summary of the financial-processing workflow.

    The coordinator receives only the counts it needs for the final
    synchronization result. Detailed financial result dictionaries
    remain available here for presentation and future API use.
    """

    financial_results: list[dict]
    missing_cost_alerts_processed: int
    missing_cost_alerts_resolved: int
    profit_snapshots_stored: int

    @property
    def financial_results_processed(
        self,
    ) -> int:
        """
        Number of stored orders financially processed.
        """

        return len(
            self.financial_results
        )


def process_financial_workflow(
    *,
    order_repository: Any,
    financial_processing_service: Any,
    alert_service: Any,
    profit_snapshot_repository: Any,
    presenter: SyncWorkflowPresenter,
) -> FinancialWorkflowResult:
    """
    Process stored-order finances and synchronize missing-cost alerts.

    Responsibilities:
        - load the persisted orders used for financial analysis
        - process each order through FinancialProcessingService
        - create/resolve missing-cost alerts
        - present financial analysis and missing-cost summaries
        - report the current persisted profit-snapshot count

    It intentionally does not own general alert-database counts or
    synchronization-audit completion.
    """

    presenter.show_financial_analysis_started()

    stored_orders_for_financials = (
        order_repository
        .get_all_orders()
    )

    financial_results = []
    missing_cost_alerts_processed = []
    missing_cost_alerts_resolved = []

    for stored_order in (
        stored_orders_for_financials
    ):
        result = (
            financial_processing_service
            .process_order(
                stored_order
            )
        )

        financial_results.append(
            result
        )

        for item_result in result["item_results"]:
            item_status = item_result["status"]

            if item_status == "missing_cost":
                alert = (
                    alert_service
                    .create_missing_cost_alert(
                        order_name=(
                            result[
                                "order_name"
                            ]
                        ),
                        missing_item=item_result,
                    )
                )

                missing_cost_alerts_processed.append(
                    alert
                )

            elif item_status in {
                "created",
                "existing_snapshot",
            }:
                sku = item_result.get(
                    "sku"
                )

                variant_id = item_result.get(
                    "shopify_variant_id"
                )

                # Custom Shopify line items can lack both
                # a variant ID and SKU. Without either,
                # there is no stable alert key to resolve.
                if variant_id or sku:
                    resolved = (
                        alert_service
                        .resolve_missing_cost_alert(
                            sku=sku,
                            variant_id=variant_id,
                        )
                    )

                    if resolved:
                        missing_cost_alerts_resolved.append(
                            {
                                "order_name": (
                                    result[
                                        "order_name"
                                    ]
                                ),
                                "sku": sku,
                                "shopify_variant_id": (
                                    variant_id
                                ),
                            }
                        )

        if result["missing_cost_count"] > 0:
            logger.warning(
                (
                    "Financial analysis incomplete for order %s. "
                    "missing_costs=%s"
                ),
                result["order_name"],
                result["missing_cost_count"],
            )

        else:
            logger.info(
                (
                    "Financial analysis complete for order %s. "
                    "snapshots_created=%s existing_snapshots=%s"
                ),
                result["order_name"],
                result["snapshots_created"],
                result["existing_snapshots"],
            )

    presenter.show_financial_processing_count(
        len(financial_results)
    )

    presenter.show_missing_cost_alert_summary(
        processed_alerts=(
            missing_cost_alerts_processed
        ),
        resolved_items=(
            missing_cost_alerts_resolved
        ),
    )

    logger.info(
        (
            "Missing-cost alert processing completed. "
            "processed=%s resolved=%s"
        ),
        len(
            missing_cost_alerts_processed
        ),
        len(
            missing_cost_alerts_resolved
        ),
    )

    presenter.show_financial_results(
        financial_results
    )

    stored_snapshot_count = (
        profit_snapshot_repository
        .count_snapshots()
    )

    logger.info(
        "Financial snapshot count: %s",
        stored_snapshot_count,
    )

    presenter.show_financial_snapshot_status(
        stored_snapshot_count
    )

    return FinancialWorkflowResult(
        financial_results=(
            financial_results
        ),
        missing_cost_alerts_processed=len(
            missing_cost_alerts_processed
        ),
        missing_cost_alerts_resolved=len(
            missing_cost_alerts_resolved
        ),
        profit_snapshots_stored=(
            stored_snapshot_count
        ),
    )
