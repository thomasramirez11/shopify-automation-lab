import logging

from repositories.alert_repository import AlertRepository


logger = logging.getLogger(__name__)


class AlertService:
    """
    Converts Shopify/business conditions into
    persistent application alerts.

    AlertRepository handles database persistence.
    AlertService decides what the alert means.
    """

    def __init__(
        self,
        alert_repository: AlertRepository,
    ):
        self.alert_repository = (
            alert_repository
        )

    def create_new_order_alert(
        self,
        order: dict,
    ) -> dict:
        """
        Create or touch an informational alert
        for a newly detected Shopify order.
        """

        order_id = order.get("id")
        order_name = order.get("name")

        if not order_id:
            raise ValueError(
                "New-order alert requires "
                "a Shopify order ID."
            )

        if not order_name:
            raise ValueError(
                "New-order alert requires "
                "a Shopify order name."
            )

        shop_money = (
            order
            .get("totalPriceSet", {})
            .get("shopMoney", {})
        )

        amount = (
            shop_money.get("amount")
            or "N/A"
        )

        currency_code = (
            shop_money.get("currencyCode")
            or "N/A"
        )

        line_items = (
            order
            .get("lineItems", {})
            .get("edges", [])
        )

        dedupe_key = (
            f"new_order:{order_id}"
        )

        title = (
            f"New Shopify order {order_name}"
        )

        message = (
            f"Order {order_name} was detected. "
            f"Total: {amount} {currency_code}. "
            f"Line items: {len(line_items)}."
        )

        alert = (
            self.alert_repository
            .create_or_touch_alert(
                alert_type="new_order",
                severity="info",
                dedupe_key=dedupe_key,
                title=title,
                message=message,
                entity_type="order",
                entity_id=order_id,
            )
        )

        logger.info(
            "Processed new-order alert "
            "for order '%s'.",
            order_name,
        )

        return alert

    def create_missing_cost_alert(
        self,
        *,
        order_name: str,
        missing_item: dict,
    ) -> dict:
        """
        Create or touch a warning alert when
        financial analysis cannot find a cost.
        """

        sku = (
            missing_item.get("sku")
            or "NO-SKU"
        )

        variant_id = missing_item.get(
            "shopify_variant_id"
        )

        dedupe_key = (
            self._build_missing_cost_dedupe_key(
                sku=sku,
                variant_id=variant_id,
            )
        )

        title = (
            f"Missing cost for {sku}"
        )

        message = (
            f"SKU {sku} has no configured "
            f"product cost. Financial analysis "
            f"for order {order_name} is "
            f"incomplete."
        )

        alert = (
            self.alert_repository
            .create_or_touch_alert(
                alert_type="missing_cost",
                severity="warning",
                dedupe_key=dedupe_key,
                title=title,
                message=message,
                entity_type="variant",
                entity_id=(
                    variant_id
                    or sku
                ),
            )
        )

        logger.warning(
            "Missing cost detected. "
            "order='%s' sku='%s' variant='%s'.",
            order_name,
            sku,
            variant_id,
        )

        return alert

    def resolve_missing_cost_alert(
        self,
        *,
        sku: str | None,
        variant_id: str | None,
    ) -> bool:
        """
        Resolve the open missing-cost alert for
        a variant once cost configuration exists.
        """

        normalized_sku = (
            sku
            or "NO-SKU"
        )

        dedupe_key = (
            self._build_missing_cost_dedupe_key(
                sku=normalized_sku,
                variant_id=variant_id,
            )
        )

        resolved = (
            self.alert_repository.resolve_alert(
                dedupe_key
            )
        )

        if resolved:
            logger.info(
                "Resolved missing-cost alert. "
                "sku='%s' variant='%s'.",
                normalized_sku,
                variant_id,
            )

        return resolved

    def create_low_inventory_alert(
        self,
        *,
        product_title: str,
        variant: dict,
        threshold: int,
    ) -> dict:
        """
        Create or touch an inventory alert when a tracked
        Shopify variant is at or below the configured threshold.
        """

        variant_id = variant.get("id")

        sku = (
            variant.get("sku")
            or "NO-SKU"
        )

        variant_title = (
            variant.get("title")
            or "Unnamed variant"
        )

        inventory_quantity = variant.get(
            "inventoryQuantity"
        )

        if isinstance(
            inventory_quantity,
            bool,
        ) or not isinstance(
            inventory_quantity,
            int,
        ):
            raise ValueError(
                "Low-inventory alert requires "
                "an integer inventory quantity."
            )

        if isinstance(
            threshold,
            bool,
        ) or not isinstance(
            threshold,
            int,
        ):
            raise ValueError(
                "Low-inventory threshold must "
                "be an integer."
            )

        if threshold < 0:
            raise ValueError(
                "Low-inventory threshold "
                "cannot be negative."
            )

        dedupe_key = (
            self._build_low_inventory_dedupe_key(
                sku=sku,
                variant_id=variant_id,
            )
        )

        display_name = sku

        if sku == "NO-SKU":
            display_name = (
                f"{product_title} / "
                f"{variant_title}"
            )

        severity = "warning"

        if inventory_quantity <= 0:
            severity = "critical"

        title = (
            f"Low inventory for {display_name}"
        )

        message = (
            f"{display_name} has "
            f"{inventory_quantity} units in stock. "
            f"The configured low-inventory "
            f"threshold is {threshold}."
        )

        alert = (
            self.alert_repository
            .create_or_touch_alert(
                alert_type="low_inventory",
                severity=severity,
                dedupe_key=dedupe_key,
                title=title,
                message=message,
                entity_type="variant",
                entity_id=(
                    variant_id
                    or sku
                ),
            )
        )

        logger.warning(
            "Low inventory detected. "
            "product='%s' variant='%s' sku='%s' "
            "inventory=%s threshold=%s.",
            product_title,
            variant_id,
            sku,
            inventory_quantity,
            threshold,
        )

        return alert

    def resolve_low_inventory_alert(
        self,
        *,
        sku: str | None,
        variant_id: str | None,
    ) -> bool:
        """
        Resolve the open low-inventory alert for a
        variant once inventory rises above the threshold.
        """

        normalized_sku = (
            sku
            or "NO-SKU"
        )

        dedupe_key = (
            self._build_low_inventory_dedupe_key(
                sku=normalized_sku,
                variant_id=variant_id,
            )
        )

        resolved = (
            self.alert_repository.resolve_alert(
                dedupe_key
            )
        )

        if resolved:
            logger.info(
                "Resolved low-inventory alert. "
                "sku='%s' variant='%s'.",
                normalized_sku,
                variant_id,
            )

        return resolved


    def create_sync_failure_alert(
        self,
        *,
        sync_run_id: int,
        error_type: str,
    ) -> dict:
        """
        Create or touch an error alert for one failed
        synchronization run.

        The alert intentionally stores only the exception
        type, not the full exception text or traceback.
        Detailed technical failure information belongs in
        the application log.
        """

        if isinstance(sync_run_id, bool) or not isinstance(
            sync_run_id,
            int,
        ):
            raise ValueError(
                "sync_run_id must be an integer."
            )

        if sync_run_id <= 0:
            raise ValueError(
                "sync_run_id must be greater than zero."
            )

        normalized_error_type = (
            error_type.strip()
            if isinstance(error_type, str)
            else ""
        )

        if not normalized_error_type:
            raise ValueError(
                "error_type is required."
            )

        dedupe_key = (
            f"sync_failure:run:{sync_run_id}"
        )

        title = (
            f"Synchronization run #{sync_run_id} failed"
        )

        message = (
            f"Synchronization run #{sync_run_id} failed "
            f"with {normalized_error_type}. "
            "Review the application log for the full "
            "technical traceback."
        )

        alert = (
            self.alert_repository
            .create_or_touch_alert(
                alert_type="sync_failure",
                severity="error",
                dedupe_key=dedupe_key,
                title=title,
                message=message,
                entity_type="sync_run",
                entity_id=str(sync_run_id),
            )
        )

        logger.error(
            "Synchronization failure alert persisted. "
            "run_id=%s error_type='%s'.",
            sync_run_id,
            normalized_error_type,
        )

        return alert

    def _build_low_inventory_dedupe_key(
        self,
        *,
        sku: str,
        variant_id: str | None,
    ) -> str:
        """
        Build a stable deduplication key for a
        low-inventory condition.

        Shopify variant ID is preferred.
        SKU is the fallback.
        """

        if variant_id:
            return (
                f"low_inventory:{variant_id}"
            )

        if sku and sku != "NO-SKU":
            return (
                f"low_inventory:sku:{sku}"
            )

        raise ValueError(
            "Cannot build low-inventory alert "
            "without a variant ID or SKU."
        )

    def _build_missing_cost_dedupe_key(
        self,
        *,
        sku: str,
        variant_id: str | None,
    ) -> str:
        """
        Create one stable deduplication key
        for a missing-cost condition.

        Shopify variant ID is preferred because
        it is the authoritative technical ID.

        SKU is the fallback.
        """

        if variant_id:
            return (
                f"missing_cost:{variant_id}"
            )

        if sku and sku != "NO-SKU":
            return (
                f"missing_cost:sku:{sku}"
            )

        raise ValueError(
            "Cannot build missing-cost alert "
            "without a variant ID or SKU."
        )