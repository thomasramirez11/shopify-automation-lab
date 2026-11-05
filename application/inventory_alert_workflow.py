from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from application.presentation_ports import (
    SyncWorkflowPresenter,
)
from application.product_sync_workflow import (
    ProductSyncState,
)
from config.settings import LOW_INVENTORY_THRESHOLD


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InventoryAlertResult:
    """
    Summary of one inventory-alert lifecycle pass.
    """

    variants_checked: int
    untracked_variants_skipped: int
    alerts_processed: int
    alerts_resolved: int


def process_inventory_alerts(
    *,
    product_state: ProductSyncState,
    alert_service: Any,
    presenter: SyncWorkflowPresenter,
    threshold: int = LOW_INVENTORY_THRESHOLD,
) -> InventoryAlertResult:
    """
    Synchronize low-inventory alert state for retrieved Shopify variants.

    This workflow:
        - skips variants explicitly marked as untracked
        - skips variants with no inventory quantity
        - creates/updates low-inventory alerts at or below the threshold
        - resolves existing low-inventory alerts above the threshold
        - presents and logs the inventory-specific summary

    It intentionally reuses the already-retrieved product snapshot and
    performs no additional Shopify API calls or product persistence.
    """

    presenter.show_low_inventory_processing_started(
        threshold
    )

    low_inventory_alerts_processed = []
    low_inventory_alerts_resolved = []
    inventory_variants_checked = 0
    untracked_variants_skipped = 0

    for product in product_state.products:
        product_title = (
            product.get("title")
            or "Unnamed product"
        )

        variant_edges = (
            product
            .get("variants", {})
            .get("edges", [])
        )

        for variant_edge in variant_edges:
            variant = (
                variant_edge.get("node")
                or {}
            )

            inventory_item = (
                variant.get("inventoryItem")
                or {}
            )

            if (
                inventory_item.get("tracked")
                is False
            ):
                untracked_variants_skipped += 1
                continue

            inventory_quantity = (
                variant.get(
                    "inventoryQuantity"
                )
            )

            if inventory_quantity is None:
                logger.info(
                    "Skipping inventory alert check "
                    "for variant '%s' because no "
                    "inventory quantity is available.",
                    variant.get("id"),
                )
                continue

            inventory_variants_checked += 1

            if inventory_quantity <= threshold:
                alert = (
                    alert_service
                    .create_low_inventory_alert(
                        product_title=product_title,
                        variant=variant,
                        threshold=threshold,
                    )
                )

                low_inventory_alerts_processed.append(
                    alert
                )

                presenter.show_active_low_inventory_alert(
                    alert
                )

            else:
                sku = variant.get("sku")
                variant_id = variant.get("id")

                if variant_id or sku:
                    resolved = (
                        alert_service
                        .resolve_low_inventory_alert(
                            sku=sku,
                            variant_id=variant_id,
                        )
                    )

                    if resolved:
                        low_inventory_alerts_resolved.append(
                            {
                                "product_title": (
                                    product_title
                                ),
                                "sku": sku,
                                "shopify_variant_id": (
                                    variant_id
                                ),
                                "inventory_quantity": (
                                    inventory_quantity
                                ),
                            }
                        )

                        presenter.show_resolved_low_inventory_alert(
                            sku=sku,
                            inventory_quantity=(
                                inventory_quantity
                            ),
                        )

    presenter.show_low_inventory_summary(
        inventory_variants_checked=(
            inventory_variants_checked
        ),
        untracked_variants_skipped=(
            untracked_variants_skipped
        ),
        processed_count=len(
            low_inventory_alerts_processed
        ),
        resolved_count=len(
            low_inventory_alerts_resolved
        ),
    )

    logger.info(
        (
            "Low-inventory alert processing "
            "completed. threshold=%s checked=%s "
            "untracked_skipped=%s processed=%s "
            "resolved=%s"
        ),
        threshold,
        inventory_variants_checked,
        untracked_variants_skipped,
        len(low_inventory_alerts_processed),
        len(low_inventory_alerts_resolved),
    )

    return InventoryAlertResult(
        variants_checked=(
            inventory_variants_checked
        ),
        untracked_variants_skipped=(
            untracked_variants_skipped
        ),
        alerts_processed=len(
            low_inventory_alerts_processed
        ),
        alerts_resolved=len(
            low_inventory_alerts_resolved
        ),
    )
