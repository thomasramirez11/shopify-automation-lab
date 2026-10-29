from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from repositories.alert_repository import AlertRepository
from repositories.order_repository import OrderRepository
from repositories.product_repository import ProductRepository
from repositories.profit_snapshot_repository import (
    ProfitSnapshotRepository,
)
from repositories.sync_run_repository import SyncRunRepository


class ReportService:
    """
    Builds structured store-health reporting data.

    This service does not print reports and does not
    write directly to SQLite.

    Repositories provide the stored data.
    ReportService combines and summarizes that data.
    """

    MONEY_QUANTIZER = Decimal("0.01")

    def __init__(
        self,
        *,
        product_repository: ProductRepository,
        order_repository: OrderRepository,
        alert_repository: AlertRepository,
        sync_run_repository: SyncRunRepository,
        profit_snapshot_repository: ProfitSnapshotRepository,
        low_inventory_threshold: int,
        report_timezone: str = "America/Bogota",
        recent_change_limit: int = 10,
    ):
        if isinstance(
            low_inventory_threshold,
            bool,
        ) or not isinstance(
            low_inventory_threshold,
            int,
        ):
            raise ValueError(
                "low_inventory_threshold must "
                "be an integer."
            )

        if low_inventory_threshold < 0:
            raise ValueError(
                "low_inventory_threshold "
                "cannot be negative."
            )

        if isinstance(
            recent_change_limit,
            bool,
        ) or not isinstance(
            recent_change_limit,
            int,
        ):
            raise ValueError(
                "recent_change_limit must "
                "be an integer."
            )

        if recent_change_limit <= 0:
            raise ValueError(
                "recent_change_limit must "
                "be greater than zero."
            )

        try:
            timezone_info = ZoneInfo(
                report_timezone
            )
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                "report_timezone must be a "
                "valid IANA timezone name."
            ) from exc

        self.product_repository = (
            product_repository
        )

        self.order_repository = (
            order_repository
        )

        self.alert_repository = (
            alert_repository
        )

        self.sync_run_repository = (
            sync_run_repository
        )

        self.profit_snapshot_repository = (
            profit_snapshot_repository
        )

        self.low_inventory_threshold = (
            low_inventory_threshold
        )

        self.report_timezone_name = (
            report_timezone
        )

        self.report_timezone = (
            timezone_info
        )

        self.recent_change_limit = (
            recent_change_limit
        )

    def generate_store_health_snapshot(
        self,
        *,
        now_utc: datetime | None = None,
    ) -> dict:
        """
        Build the current V1 store-health snapshot.

        now_utc is optional.

        Normally the current UTC time is used.

        Allowing a timestamp to be supplied also makes
        time-based reporting logic easier to test later.
        """

        current_utc = (
            self._normalize_now_utc(
                now_utc
            )
        )

        current_local = (
            current_utc.astimezone(
                self.report_timezone
            )
        )

        products = (
            self.product_repository
            .get_all_products()
        )

        variants = (
            self.product_repository
            .get_all_variants()
        )

        recent_variant_changes = (
            self.product_repository
            .get_recent_variant_changes(
                limit=self.recent_change_limit
            )
        )

        orders = (
            self.order_repository
            .get_all_orders()
        )

        orders_today = (
            self._filter_orders_for_local_date(
                orders=orders,
                local_date=current_local.date(),
            )
        )

        profit_snapshots = (
            self.profit_snapshot_repository
            .get_all_snapshots()
        )

        today_order_ids = {
            order["shopify_order_id"]
            for order in orders_today
        }

        today_profit_snapshots = [
            snapshot
            for snapshot in profit_snapshots
            if snapshot["shopify_order_id"]
            in today_order_ids
        ]

        open_alerts = (
            self.alert_repository
            .get_open_alerts()
        )

        recent_sync_runs = (
            self.sync_run_repository
            .get_recent_runs(
                limit=5
            )
        )

        store_summary = (
            self._build_store_summary(
                products=products,
                variants=variants,
            )
        )

        order_summary = (
            self._build_order_summary(
                orders=orders,
                orders_today=orders_today,
            )
        )

        profitability_summary = (
            self._build_profitability_summary(
                orders=orders,
                snapshots=profit_snapshots,
            )
        )

        today_summary = (
            self._build_daily_performance_summary(
                local_date=current_local.date(),
                orders=orders_today,
                snapshots=today_profit_snapshots,
            )
        )

        inventory_summary = (
            self._build_inventory_summary(
                variants=variants
            )
        )

        recent_changes_summary = (
            self._build_recent_changes_summary(
                changes=recent_variant_changes
            )
        )

        alert_summary = (
            self._build_alert_summary(
                open_alerts=open_alerts
            )
        )

        sync_summary = (
            self._build_sync_summary(
                recent_sync_runs=recent_sync_runs
            )
        )

        health_summary = (
            self._build_health_summary(
                inventory_summary=inventory_summary,
                profitability_summary=(
                    profitability_summary
                ),
                alert_summary=alert_summary,
                sync_summary=sync_summary,
                open_alerts=open_alerts,
            )
        )

        return {
            "generated_at_utc":
                current_utc.isoformat(),

            "report_context": {
                "timezone":
                    self.report_timezone_name,

                "local_date":
                    current_local
                    .date()
                    .isoformat(),
            },

            "health":
                health_summary,

            "store":
                store_summary,

            "orders":
                order_summary,

            "profitability":
                profitability_summary,

            "today":
                today_summary,

            "inventory":
                inventory_summary,

            "recent_changes":
                recent_changes_summary,

            "alerts":
                alert_summary,

            "sync_health":
                sync_summary,
        }

    def _build_store_summary(
        self,
        *,
        products: list,
        variants: list,
    ) -> dict:
        """
        Summarize currently monitored Shopify data.
        """

        return {
            "products_monitored":
                len(products),

            "variants_monitored":
                len(variants),
        }

    def _build_order_summary(
        self,
        *,
        orders: list,
        orders_today: list,
    ) -> dict:
        """
        Summarize stored order activity.

        orders_today is already filtered using the
        configured report timezone.
        """

        latest_order = (
            orders[0]
            if orders
            else None
        )

        return {
            "total_orders":
                len(orders),

            "total_line_items":
                self.order_repository
                .count_line_items(),

            "orders_today":
                len(orders_today),

            "latest_order_name":
                (
                    latest_order[
                        "order_name"
                    ]
                    if latest_order
                    else None
                ),

            "latest_order_created_at":
                (
                    latest_order[
                        "created_at"
                    ]
                    if latest_order
                    else None
                ),
        }

    def _filter_orders_for_local_date(
        self,
        *,
        orders: list,
        local_date,
    ) -> list:
        """
        Return orders whose Shopify creation timestamp
        belongs to one calendar date in the configured
        report timezone.
        """

        matching_orders = []

        for order in orders:
            created_at = (
                order.get("created_at")
            )

            if not created_at:
                continue

            created_utc = (
                self._parse_shopify_datetime(
                    created_at
                )
            )

            created_local = (
                created_utc.astimezone(
                    self.report_timezone
                )
            )

            if (
                created_local.date()
                == local_date
            ):
                matching_orders.append(
                    order
                )

        return matching_orders

    def _build_daily_performance_summary(
        self,
        *,
        local_date,
        orders: list,
        snapshots: list,
    ) -> dict:
        """
        Summarize financial performance for one
        local business date.

        Order created_at decides which business day
        receives the sale.

        Snapshot calculated_at is intentionally not
        used for daily attribution.
        """

        financial_summary = (
            self._build_profitability_summary(
                orders=orders,
                snapshots=snapshots,
            )
        )

        return {
            "local_date":
                local_date.isoformat(),

            "orders":
                len(orders),

            "orders_financially_complete":
                financial_summary[
                    "orders_financially_complete"
                ],

            "orders_financially_incomplete":
                financial_summary[
                    "orders_financially_incomplete"
                ],

            "profit_snapshots":
                financial_summary[
                    "profit_snapshots"
                ],

            "currency_count":
                financial_summary[
                    "currency_count"
                ],

            "currency_codes":
                financial_summary[
                    "currency_codes"
                ],

            "single_currency_code":
                financial_summary[
                    "single_currency_code"
                ],

            "merchandise_revenue":
                financial_summary[
                    "merchandise_revenue"
                ],

            "product_cost":
                financial_summary[
                    "product_cost"
                ],

            "estimated_gross_profit":
                financial_summary[
                    "estimated_gross_profit"
                ],

            "gross_margin_percent":
                financial_summary[
                    "gross_margin_percent"
                ],

            "by_currency":
                financial_summary[
                    "by_currency"
                ],
        }

    def _build_profitability_summary(
        self,
        *,
        orders: list,
        snapshots: list,
    ) -> dict:
        """
        Summarize immutable historical profit data.

        Financial totals are grouped by currency so the
        report never adds USD, COP, or other currencies
        together as though they were equivalent.
        """

        snapshots_by_order = {}

        for snapshot in snapshots:
            order_id = snapshot["shopify_order_id"]

            snapshots_by_order.setdefault(
                order_id,
                [],
            ).append(snapshot)

        complete_orders = 0
        incomplete_orders = 0

        for order in orders:
            order_id = order["shopify_order_id"]

            line_items = (
                self.order_repository
                .get_line_items_for_order(
                    order_id
                )
            )

            order_snapshots = (
                snapshots_by_order.get(
                    order_id,
                    [],
                )
            )

            if (
                line_items
                and len(order_snapshots)
                == len(line_items)
            ):
                complete_orders += 1
            else:
                incomplete_orders += 1

        totals_by_currency = {}

        for snapshot in snapshots:
            currency_code = (
                snapshot["currency_code"]
                .strip()
                .upper()
            )

            currency_totals = (
                totals_by_currency.setdefault(
                    currency_code,
                    {
                        "merchandise_revenue": Decimal("0.00"),
                        "product_cost": Decimal("0.00"),
                        "estimated_gross_profit": Decimal("0.00"),
                        "quantity": 0,
                        "line_items": 0,
                    },
                )
            )

            currency_totals[
                "merchandise_revenue"
            ] += self._to_decimal(
                snapshot["line_revenue"],
                field_name="line_revenue",
            )

            currency_totals[
                "product_cost"
            ] += self._to_decimal(
                snapshot["line_cost"],
                field_name="line_cost",
            )

            currency_totals[
                "estimated_gross_profit"
            ] += self._to_decimal(
                snapshot[
                    "estimated_gross_profit"
                ],
                field_name=(
                    "estimated_gross_profit"
                ),
            )

            currency_totals[
                "quantity"
            ] += int(snapshot["quantity"])

            currency_totals[
                "line_items"
            ] += 1

        formatted_currency_totals = {}

        for (
            currency_code,
            currency_totals,
        ) in totals_by_currency.items():
            revenue = currency_totals[
                "merchandise_revenue"
            ]

            gross_profit = currency_totals[
                "estimated_gross_profit"
            ]

            margin_percent = (
                None
                if revenue == 0
                else (
                    gross_profit
                    / revenue
                    * Decimal("100")
                ).quantize(
                    self.MONEY_QUANTIZER,
                    rounding=ROUND_HALF_UP,
                )
            )

            formatted_currency_totals[
                currency_code
            ] = {
                "merchandise_revenue":
                    self._money_text(revenue),

                "product_cost":
                    self._money_text(
                        currency_totals[
                            "product_cost"
                        ]
                    ),

                "estimated_gross_profit":
                    self._money_text(
                        gross_profit
                    ),

                "gross_margin_percent":
                    (
                        self._money_text(
                            margin_percent
                        )
                        if margin_percent
                        is not None
                        else None
                    ),

                "total_quantity":
                    currency_totals[
                        "quantity"
                    ],

                "financial_line_items":
                    currency_totals[
                        "line_items"
                    ],
            }

        currency_codes = sorted(
            formatted_currency_totals.keys()
        )

        single_currency_code = (
            currency_codes[0]
            if len(currency_codes) == 1
            else None
        )

        single_currency_summary = (
            formatted_currency_totals.get(
                single_currency_code
            )
            if single_currency_code
            else None
        )

        return {
            "orders_total": len(orders),

            "orders_financially_complete":
                complete_orders,

            "orders_financially_incomplete":
                incomplete_orders,

            "profit_snapshots":
                len(snapshots),

            "currency_count":
                len(currency_codes),

            "currency_codes":
                currency_codes,

            "single_currency_code":
                single_currency_code,

            "merchandise_revenue":
                (
                    single_currency_summary[
                        "merchandise_revenue"
                    ]
                    if single_currency_summary
                    else None
                ),

            "product_cost":
                (
                    single_currency_summary[
                        "product_cost"
                    ]
                    if single_currency_summary
                    else None
                ),

            "estimated_gross_profit":
                (
                    single_currency_summary[
                        "estimated_gross_profit"
                    ]
                    if single_currency_summary
                    else None
                ),

            "gross_margin_percent":
                (
                    single_currency_summary[
                        "gross_margin_percent"
                    ]
                    if single_currency_summary
                    else None
                ),

            "by_currency":
                formatted_currency_totals,
        }

    def _build_inventory_summary(
        self,
        *,
        variants: list,
    ) -> dict:
        """
        Summarize inventory state using the
        configured low-inventory threshold.
        """

        low_inventory_count = 0
        out_of_stock_count = 0
        inventory_known_count = 0

        for variant in variants:
            inventory_quantity = (
                variant.get(
                    "inventory_quantity"
                )
            )

            if inventory_quantity is None:
                continue

            inventory_known_count += 1

            if inventory_quantity <= 0:
                out_of_stock_count += 1

            if (
                inventory_quantity
                <= self.low_inventory_threshold
            ):
                low_inventory_count += 1

        return {
            "low_inventory_threshold":
                self.low_inventory_threshold,

            "inventory_known_variants":
                inventory_known_count,

            "low_inventory_variants":
                low_inventory_count,

            "out_of_stock_variants":
                out_of_stock_count,
        }

    def _build_recent_changes_summary(
        self,
        *,
        changes: list,
    ) -> dict:
        """
        Summarize the most recent recorded variant
        price and inventory changes.

        The repository already returns newest first.
        """

        price_changes = 0
        inventory_changes = 0
        items = []

        for change in changes:
            field_name = change.get(
                "field_name"
            )

            if field_name == "price":
                price_changes += 1

            if field_name == "inventory_quantity":
                inventory_changes += 1

            items.append(
                {
                    "id":
                        change["id"],

                    "detected_at":
                        change["detected_at"],

                    "shopify_variant_id":
                        change[
                            "shopify_variant_id"
                        ],

                    "product_title":
                        change[
                            "product_title"
                        ],

                    "variant_title":
                        change[
                            "variant_title"
                        ],

                    "sku":
                        change.get("sku"),

                    "field_name":
                        field_name,

                    "old_value":
                        change.get("old_value"),

                    "new_value":
                        change.get("new_value"),
                }
            )

        return {
            "limit":
                self.recent_change_limit,

            "changes_returned":
                len(items),

            "price_changes":
                price_changes,

            "inventory_changes":
                inventory_changes,

            "items":
                items,
        }

    def _build_alert_summary(
        self,
        *,
        open_alerts: list,
    ) -> dict:
        """
        Summarize alerts requiring attention now.
        """

        severity_counts = {
            "info": 0,
            "warning": 0,
            "error": 0,
            "critical": 0,
        }

        type_counts = {
            "new_order": 0,
            "missing_cost": 0,
            "low_inventory": 0,
            "sync_failure": 0,
        }

        for alert in open_alerts:
            severity = alert.get(
                "severity"
            )

            alert_type = alert.get(
                "alert_type"
            )

            if severity in severity_counts:
                severity_counts[
                    severity
                ] += 1

            if alert_type in type_counts:
                type_counts[
                    alert_type
                ] += 1

        return {
            "open_total":
                len(open_alerts),

            "by_severity":
                severity_counts,

            "by_type":
                type_counts,
        }

    def _build_sync_summary(
        self,
        *,
        recent_sync_runs: list,
    ) -> dict:
        """
        Summarize synchronization health using
        the most recent audit history.
        """

        if not recent_sync_runs:
            return {
                "latest_run_id": None,
                "latest_status": None,
                "latest_started_at": None,
                "latest_completed_at": None,
                "recent_runs_checked": 0,
                "recent_failures": 0,
            }

        latest_run = (
            recent_sync_runs[0]
        )

        recent_failure_count = sum(
            1
            for run in recent_sync_runs
            if run["status"] == "failed"
        )

        return {
            "latest_run_id":
                latest_run["id"],

            "latest_status":
                latest_run["status"],

            "latest_started_at":
                latest_run[
                    "started_at"
                ],

            "latest_completed_at":
                latest_run[
                    "completed_at"
                ],

            "recent_runs_checked":
                len(recent_sync_runs),

            "recent_failures":
                recent_failure_count,
        }

    def _build_health_summary(
        self,
        *,
        inventory_summary: dict,
        profitability_summary: dict,
        alert_summary: dict,
        sync_summary: dict,
        open_alerts: list,
    ) -> dict:
        """
        Build a transparent current store-health status.

        Health is rule-based rather than an opaque score.

        Event alerts such as new_order and sync_failure are
        not treated as permanent current conditions by
        themselves. Current sync state and recent sync
        history are evaluated separately.
        """

        critical_reasons = []
        attention_reasons = []

        latest_status = (
            sync_summary.get(
                "latest_status"
            )
        )

        out_of_stock_count = (
            inventory_summary.get(
                "out_of_stock_variants",
                0,
            )
        )

        low_inventory_count = (
            inventory_summary.get(
                "low_inventory_variants",
                0,
            )
        )

        incomplete_orders = (
            profitability_summary.get(
                "orders_financially_incomplete",
                0,
            )
        )

        recent_failures = (
            sync_summary.get(
                "recent_failures",
                0,
            )
        )

        missing_cost_alerts = sum(
            1
            for alert in open_alerts
            if alert.get("alert_type")
            == "missing_cost"
        )

        if latest_status == "failed":
            critical_reasons.append(
                {
                    "code":
                        "latest_sync_failed",

                    "message":
                        "The latest synchronization "
                        "run failed.",
                }
            )

        if out_of_stock_count > 0:
            critical_reasons.append(
                {
                    "code":
                        "out_of_stock",

                    "message":
                        (
                            f"{out_of_stock_count} "
                            "variant(s) are out of stock."
                        ),
                }
            )

        if low_inventory_count > 0:
            attention_reasons.append(
                {
                    "code":
                        "low_inventory",

                    "message":
                        (
                            f"{low_inventory_count} "
                            "variant(s) are at or below "
                            "the low-inventory threshold."
                        ),
                }
            )

        if incomplete_orders > 0:
            attention_reasons.append(
                {
                    "code":
                        "incomplete_financial_data",

                    "message":
                        (
                            f"{incomplete_orders} "
                            "order(s) have incomplete "
                            "financial data."
                        ),
                }
            )

        if missing_cost_alerts > 0:
            attention_reasons.append(
                {
                    "code":
                        "missing_cost",

                    "message":
                        (
                            f"{missing_cost_alerts} "
                            "open missing-cost alert(s) "
                            "require configuration."
                        ),
                }
            )

        if recent_failures > 0:
            attention_reasons.append(
                {
                    "code":
                        "recent_sync_failures",

                    "message":
                        (
                            f"{recent_failures} failed "
                            "synchronization run(s) were "
                            "found in the recent history."
                        ),
                }
            )

        if critical_reasons:
            status = "critical"
            headline = (
                "Immediate store attention is required."
            )
        elif attention_reasons:
            status = "attention"
            headline = (
                "The store is operating, but some "
                "items require attention."
            )
        else:
            status = "healthy"
            headline = (
                "No current health issues were detected."
            )

        reasons = (
            critical_reasons
            + attention_reasons
        )

        return {
            "status":
                status,

            "headline":
                headline,

            "reason_count":
                len(reasons),

            "critical_reason_count":
                len(critical_reasons),

            "attention_reason_count":
                len(attention_reasons),

            "reasons":
                reasons,

            "checks": {
                "latest_sync_successful":
                    latest_status == "success",

                "no_out_of_stock_variants":
                    out_of_stock_count == 0,

                "no_low_inventory_variants":
                    low_inventory_count == 0,

                "financial_data_complete":
                    incomplete_orders == 0,

                "no_open_missing_cost_alerts":
                    missing_cost_alerts == 0,

                "no_recent_sync_failures":
                    recent_failures == 0,
            },

            "context": {
                "open_alerts":
                    alert_summary.get(
                        "open_total",
                        0,
                    ),

                "recent_runs_checked":
                    sync_summary.get(
                        "recent_runs_checked",
                        0,
                    ),
            },
        }

    def _parse_shopify_datetime(
        self,
        value: str,
    ) -> datetime:
        """
        Convert a stored Shopify ISO-8601 timestamp
        into an aware Python datetime.

        Shopify commonly uses timestamps ending in Z,
        which represents UTC.
        """

        normalized_value = (
            value.replace(
                "Z",
                "+00:00",
            )
        )

        parsed = datetime.fromisoformat(
            normalized_value
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed.astimezone(
            timezone.utc
        )

    def _normalize_now_utc(
        self,
        value: datetime | None,
    ) -> datetime:
        """
        Return an aware UTC datetime.

        If no timestamp is supplied, use now.
        """

        if value is None:
            return (
                datetime.now(
                    timezone.utc
                )
                .replace(
                    microsecond=0
                )
            )

        if not isinstance(
            value,
            datetime,
        ):
            raise ValueError(
                "now_utc must be a datetime "
                "or None."
            )

        if value.tzinfo is None:
            raise ValueError(
                "now_utc must include "
                "timezone information."
            )

        return (
            value.astimezone(
                timezone.utc
            )
            .replace(
                microsecond=0
            )
        )

    def _to_decimal(
        self,
        value,
        *,
        field_name: str,
    ) -> Decimal:
        """
        Safely convert stored financial text
        into Decimal.
        """

        try:
            return Decimal(str(value))
        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                f"{field_name} must be a "
                "valid decimal value."
            ) from exc

    def _money_text(
        self,
        value: Decimal,
    ) -> str:
        """
        Return a two-decimal-place financial string.
        """

        return format(
            value.quantize(
                self.MONEY_QUANTIZER,
                rounding=ROUND_HALF_UP,
            ),
            ".2f",
        )
