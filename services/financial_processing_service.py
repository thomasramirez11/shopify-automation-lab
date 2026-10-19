from repositories.cost_repository import CostRepository
from repositories.order_repository import OrderRepository
from repositories.profit_snapshot_repository import (
    ProfitSnapshotRepository,
)
from services.profit_service import ProfitService


class FinancialProcessingService:
    """
    Coordinates order data, configured costs,
    profit calculations, and historical snapshots.
    """

    COMPLETE_STATUSES = {
        "created",
        "existing_snapshot",
    }

    def __init__(
        self,
        order_repository: OrderRepository,
        cost_repository: CostRepository,
        snapshot_repository: ProfitSnapshotRepository,
        profit_service: ProfitService,
    ):
        self.order_repository = order_repository
        self.cost_repository = cost_repository
        self.snapshot_repository = snapshot_repository
        self.profit_service = profit_service

    def process_order_by_name(
        self,
        order_name: str,
    ) -> dict:
        """
        Process one stored Shopify order by its
        human-readable order name.
        """

        order = (
            self.order_repository.get_order_by_name(
                order_name
            )
        )

        if order is None:
            raise ValueError(
                f"Order {order_name} was not found."
            )

        return self.process_order(order)

    def process_order(
        self,
        order: dict,
    ) -> dict:
        """
        Process all stored line items for one order.

        Creates missing profit snapshots when costs
        are available.

        Orders with missing costs are marked incomplete
        instead of receiving incorrect profit estimates.
        """

        order_id = order["shopify_order_id"]

        line_items = (
            self.order_repository
            .get_line_items_for_order(
                order_id
            )
        )

        item_results = []

        for line_item in line_items:
            result = self.process_line_item(
                order=order,
                line_item=line_item,
            )

            item_results.append(result)

        complete_items = [
            result
            for result in item_results
            if result["status"]
            in self.COMPLETE_STATUSES
        ]

        missing_cost_items = [
            result
            for result in item_results
            if result["status"]
            == "missing_cost"
        ]

        financial_status = "complete"

        if len(complete_items) != len(line_items):
            financial_status = "incomplete"

        snapshots = (
            self.snapshot_repository
            .get_snapshots_for_order(
                order_id
            )
        )

        summary = None

        if (
            financial_status == "complete"
            and snapshots
        ):
            summary = (
                self.profit_service
                .calculate_order_summary(
                    snapshots
                )
            )

        return {
            "shopify_order_id":
                order_id,

            "order_name":
                order["order_name"],

            "financial_status":
                financial_status,

            "line_items_seen":
                len(line_items),

            "snapshots_available":
                len(snapshots),

            "snapshots_created":
                sum(
                    1
                    for result in item_results
                    if result["status"]
                    == "created"
                ),

            "existing_snapshots":
                sum(
                    1
                    for result in item_results
                    if result["status"]
                    == "existing_snapshot"
                ),

            "missing_cost_count":
                len(missing_cost_items),

            "missing_cost_items":
                missing_cost_items,

            "summary":
                summary,

            "item_results":
                item_results,
        }

    def process_line_item(
        self,
        order: dict,
        line_item: dict,
    ) -> dict:
        """
        Process one order line item.

        Possible statuses:
            created
            existing_snapshot
            missing_cost
        """

        line_item_id = (
            line_item["shopify_line_item_id"]
        )

        existing_snapshot = (
            self.snapshot_repository
            .get_snapshot_by_line_item_id(
                line_item_id
            )
        )

        if existing_snapshot is not None:
            return {
                "status":
                    "existing_snapshot",

                "shopify_line_item_id":
                    line_item_id,

                "sku":
                    line_item.get("sku"),

                "shopify_variant_id":
                    line_item.get(
                        "shopify_variant_id"
                    ),

                "snapshot":
                    existing_snapshot,
            }

        cost = self._find_cost(
            line_item
        )

        if cost is None:
            return {
                "status":
                    "missing_cost",

                "shopify_line_item_id":
                    line_item_id,

                "sku":
                    line_item.get("sku"),

                "shopify_variant_id":
                    line_item.get(
                        "shopify_variant_id"
                    ),

                "snapshot":
                    None,
            }

        calculation = (
            self.profit_service
            .calculate_line_item_profit(
                unit_sale_price=line_item[
                    "unit_price"
                ],
                unit_cost=cost[
                    "unit_cost"
                ],
                quantity=line_item[
                    "quantity"
                ],
                sale_currency=order[
                    "currency_code"
                ],
                cost_currency=cost[
                    "currency_code"
                ],
            )
        )

        snapshot_created = (
            self.snapshot_repository
            .save_snapshot(
                shopify_line_item_id=(
                    line_item_id
                ),
                shopify_order_id=order[
                    "shopify_order_id"
                ],
                shopify_variant_id=line_item.get(
                    "shopify_variant_id"
                ),
                sku=line_item.get("sku"),
                calculation=calculation,
                cost_source=cost[
                    "cost_source"
                ],
            )
        )

        snapshot = (
            self.snapshot_repository
            .get_snapshot_by_line_item_id(
                line_item_id
            )
        )

        status = "created"

        if not snapshot_created:
            status = "existing_snapshot"

        return {
            "status":
                status,

            "shopify_line_item_id":
                line_item_id,

            "sku":
                line_item.get("sku"),

            "shopify_variant_id":
                line_item.get(
                    "shopify_variant_id"
                ),

            "snapshot":
                snapshot,
        }

    def _find_cost(
        self,
        line_item: dict,
    ):
        """
        Find the current configured cost for a line item.

        Shopify variant ID is preferred because it is
        the authoritative technical identifier.

        SKU is used as a fallback when necessary.
        """

        variant_id = line_item.get(
            "shopify_variant_id"
        )

        if variant_id:
            cost = (
                self.cost_repository
                .get_cost_by_variant_id(
                    variant_id
                )
            )

            if cost is not None:
                return cost

        sku = line_item.get("sku")

        if sku:
            return (
                self.cost_repository
                .get_cost_by_sku(
                    sku
                )
            )

        return None