class TerminalReportFormatter:
    """
    Convert structured ReportService data into a clean,
    human-readable terminal report.

    This class does not query Shopify or SQLite.
    It only formats data that has already been prepared
    by ReportService.
    """

    def __init__(
        self,
        *,
        recent_changes_to_show: int = 5,
    ):
        if isinstance(
            recent_changes_to_show,
            bool,
        ) or not isinstance(
            recent_changes_to_show,
            int,
        ):
            raise ValueError(
                "recent_changes_to_show must "
                "be an integer."
            )

        if recent_changes_to_show <= 0:
            raise ValueError(
                "recent_changes_to_show must "
                "be greater than zero."
            )

        self.recent_changes_to_show = (
            recent_changes_to_show
        )

    def format_daily_report(
        self,
        report: dict,
    ) -> str:
        """
        Return the complete terminal daily report
        as one string.
        """

        if not isinstance(
            report,
            dict,
        ):
            raise ValueError(
                "report must be a dictionary."
            )

        lines = []

        self._add_header(
            lines=lines,
            report=report,
        )

        self._add_health_section(
            lines=lines,
            health=report.get(
                "health",
                {},
            ),
        )

        self._add_today_section(
            lines=lines,
            today=report.get(
                "today",
                {},
            ),
        )

        self._add_historical_section(
            lines=lines,
            profitability=report.get(
                "profitability",
                {},
            ),
        )

        self._add_inventory_section(
            lines=lines,
            inventory=report.get(
                "inventory",
                {},
            ),
        )

        self._add_alert_section(
            lines=lines,
            alerts=report.get(
                "alerts",
                {},
            ),
        )

        self._add_recent_changes_section(
            lines=lines,
            recent_changes=report.get(
                "recent_changes",
                {},
            ),
        )

        self._add_sync_section(
            lines=lines,
            sync_health=report.get(
                "sync_health",
                {},
            ),
        )

        return "\n".join(lines)

    def _add_header(
        self,
        *,
        lines: list,
        report: dict,
    ) -> None:
        """
        Add report title and business-date context.
        """

        report_context = report.get(
            "report_context",
            {},
        )

        store = report.get(
            "store",
            {},
        )

        lines.extend(
            [
                (
                    "SHOPIFY AUTOMATION LAB "
                    "— DAILY REPORT"
                ),
                "=" * 48,
                (
                    "Business date: "
                    f"{self._display_value(report_context.get('local_date'))}"
                ),
                (
                    "Timezone: "
                    f"{self._display_value(report_context.get('timezone'))}"
                ),
                (
                    "Generated UTC: "
                    f"{self._display_value(report.get('generated_at_utc'))}"
                ),
                (
                    "Products / Variants monitored: "
                    f"{self._display_value(store.get('products_monitored'))}"
                    " / "
                    f"{self._display_value(store.get('variants_monitored'))}"
                ),
                "",
            ]
        )

    def _add_health_section(
        self,
        *,
        lines: list,
        health: dict,
    ) -> None:
        """
        Add current store-health interpretation.
        """

        status = (
            health.get(
                "status",
                "unknown",
            )
        )

        lines.extend(
            [
                "STORE HEALTH",
                "-" * 48,
                f"Status: {str(status).upper()}",
                (
                    "Summary: "
                    f"{self._display_value(health.get('headline'))}"
                ),
            ]
        )

        reasons = health.get(
            "reasons",
            [],
        )

        if reasons:
            lines.append("Reasons:")

            for reason in reasons:
                lines.append(
                    "  - "
                    f"{self._display_value(reason.get('message'))}"
                )
        else:
            lines.append(
                "Reasons: None"
            )

        lines.append("")

    def _add_today_section(
        self,
        *,
        lines: list,
        today: dict,
    ) -> None:
        """
        Add current local business-day performance.
        """

        lines.extend(
            [
                "TODAY",
                "-" * 48,
                (
                    "Orders: "
                    f"{self._display_value(today.get('orders'))}"
                ),
                (
                    "Financially complete: "
                    f"{self._display_value(today.get('orders_financially_complete'))}"
                ),
                (
                    "Financially incomplete: "
                    f"{self._display_value(today.get('orders_financially_incomplete'))}"
                ),
            ]
        )

        self._add_financial_lines(
            lines=lines,
            financial_data=today,
        )

        lines.append("")

    def _add_historical_section(
        self,
        *,
        lines: list,
        profitability: dict,
    ) -> None:
        """
        Add all-time historical profitability.
        """

        lines.extend(
            [
                "HISTORICAL PERFORMANCE",
                "-" * 48,
                (
                    "Orders: "
                    f"{self._display_value(profitability.get('orders_total'))}"
                ),
                (
                    "Financially complete: "
                    f"{self._display_value(profitability.get('orders_financially_complete'))}"
                ),
                (
                    "Financially incomplete: "
                    f"{self._display_value(profitability.get('orders_financially_incomplete'))}"
                ),
                (
                    "Profit snapshots: "
                    f"{self._display_value(profitability.get('profit_snapshots'))}"
                ),
            ]
        )

        self._add_financial_lines(
            lines=lines,
            financial_data=profitability,
        )

        lines.append("")

    def _add_financial_lines(
        self,
        *,
        lines: list,
        financial_data: dict,
    ) -> None:
        """
        Add financial totals safely for either
        single-currency or multi-currency data.
        """

        single_currency = (
            financial_data.get(
                "single_currency_code"
            )
        )

        if single_currency:
            lines.extend(
                [
                    (
                        "Merchandise revenue: "
                        f"{self._money_value(financial_data.get('merchandise_revenue'), single_currency)}"
                    ),
                    (
                        "Product cost: "
                        f"{self._money_value(financial_data.get('product_cost'), single_currency)}"
                    ),
                    (
                        "Estimated gross profit: "
                        f"{self._money_value(financial_data.get('estimated_gross_profit'), single_currency)}"
                    ),
                    (
                        "Gross margin: "
                        f"{self._percent_value(financial_data.get('gross_margin_percent'))}"
                    ),
                ]
            )

            return

        by_currency = financial_data.get(
            "by_currency",
            {},
        )

        if not by_currency:
            lines.extend(
                [
                    "Merchandise revenue: N/A",
                    "Product cost: N/A",
                    "Estimated gross profit: N/A",
                    "Gross margin: N/A",
                ]
            )

            return

        lines.append(
            "Financial totals by currency:"
        )

        for currency_code in sorted(
            by_currency
        ):
            currency_data = (
                by_currency[
                    currency_code
                ]
            )

            lines.extend(
                [
                    f"  {currency_code}",
                    (
                        "    Revenue: "
                        f"{self._money_value(currency_data.get('merchandise_revenue'), currency_code)}"
                    ),
                    (
                        "    Cost: "
                        f"{self._money_value(currency_data.get('product_cost'), currency_code)}"
                    ),
                    (
                        "    Gross profit: "
                        f"{self._money_value(currency_data.get('estimated_gross_profit'), currency_code)}"
                    ),
                    (
                        "    Margin: "
                        f"{self._percent_value(currency_data.get('gross_margin_percent'))}"
                    ),
                ]
            )

    def _add_inventory_section(
        self,
        *,
        lines: list,
        inventory: dict,
    ) -> None:
        """
        Add current inventory health.
        """

        lines.extend(
            [
                "INVENTORY",
                "-" * 48,
                (
                    "Configured low threshold: "
                    f"{self._display_value(inventory.get('low_inventory_threshold'))}"
                ),
                (
                    "Variants with known inventory: "
                    f"{self._display_value(inventory.get('inventory_known_variants'))}"
                ),
                (
                    "Low inventory variants: "
                    f"{self._display_value(inventory.get('low_inventory_variants'))}"
                ),
                (
                    "Out of stock variants: "
                    f"{self._display_value(inventory.get('out_of_stock_variants'))}"
                ),
                "",
            ]
        )

    def _add_alert_section(
        self,
        *,
        lines: list,
        alerts: dict,
    ) -> None:
        """
        Add current open alert counts.
        """

        by_severity = alerts.get(
            "by_severity",
            {},
        )

        by_type = alerts.get(
            "by_type",
            {},
        )

        lines.extend(
            [
                "OPEN ALERTS",
                "-" * 48,
                (
                    "Total: "
                    f"{self._display_value(alerts.get('open_total'))}"
                ),
                (
                    "Severity — "
                    f"Info: {by_severity.get('info', 0)} | "
                    f"Warning: {by_severity.get('warning', 0)} | "
                    f"Error: {by_severity.get('error', 0)} | "
                    f"Critical: {by_severity.get('critical', 0)}"
                ),
                (
                    "Types — "
                    f"New order: {by_type.get('new_order', 0)} | "
                    f"Missing cost: {by_type.get('missing_cost', 0)} | "
                    f"Low inventory: {by_type.get('low_inventory', 0)} | "
                    f"Sync failure: {by_type.get('sync_failure', 0)}"
                ),
                "",
            ]
        )

    def _add_recent_changes_section(
        self,
        *,
        lines: list,
        recent_changes: dict,
    ) -> None:
        """
        Add a readable recent product-change feed.
        """

        items = recent_changes.get(
            "items",
            [],
        )

        visible_items = items[
            :self.recent_changes_to_show
        ]

        lines.extend(
            [
                "RECENT STORE CHANGES",
                "-" * 48,
                (
                    "Recent changes available: "
                    f"{self._display_value(recent_changes.get('changes_returned'))}"
                ),
            ]
        )

        if not visible_items:
            lines.append(
                "No recent product changes recorded."
            )
            lines.append("")
            return

        for change in visible_items:
            identifier = (
                change.get("sku")
                or self._build_variant_label(
                    change
                )
            )

            field_name = change.get(
                "field_name"
            )

            if field_name == "inventory_quantity":
                field_label = "Inventory"
            elif field_name == "price":
                field_label = "Price"
            else:
                field_label = (
                    self._display_value(
                        field_name
                    )
                )

            lines.append(
                "  - "
                f"{identifier} | "
                f"{field_label}: "
                f"{self._display_value(change.get('old_value'))}"
                " -> "
                f"{self._display_value(change.get('new_value'))}"
                " | "
                f"{self._display_value(change.get('detected_at'))}"
            )

        hidden_count = (
            len(items)
            - len(visible_items)
        )

        if hidden_count > 0:
            lines.append(
                f"  ... {hidden_count} more change(s) "
                "available in report data."
            )

        lines.append("")

    def _add_sync_section(
        self,
        *,
        lines: list,
        sync_health: dict,
    ) -> None:
        """
        Add synchronization-health information.
        """

        latest_status = sync_health.get(
            "latest_status"
        )

        latest_status_text = (
            str(latest_status).upper()
            if latest_status is not None
            else "N/A"
        )

        latest_run_id = sync_health.get(
            "latest_run_id"
        )

        run_label = (
            f"#{latest_run_id}"
            if latest_run_id is not None
            else "N/A"
        )

        lines.extend(
            [
                "SYNC HEALTH",
                "-" * 48,
                (
                    "Latest run: "
                    f"{run_label} | {latest_status_text}"
                ),
                (
                    "Started: "
                    f"{self._display_value(sync_health.get('latest_started_at'))}"
                ),
                (
                    "Completed: "
                    f"{self._display_value(sync_health.get('latest_completed_at'))}"
                ),
                (
                    "Recent runs checked: "
                    f"{self._display_value(sync_health.get('recent_runs_checked'))}"
                ),
                (
                    "Recent failures: "
                    f"{self._display_value(sync_health.get('recent_failures'))}"
                ),
                "",
                "=" * 48,
                "END OF REPORT",
            ]
        )

    def _build_variant_label(
        self,
        change: dict,
    ) -> str:
        """
        Build a readable fallback when a SKU is missing.
        """

        product_title = (
            change.get(
                "product_title"
            )
            or "Unknown product"
        )

        variant_title = (
            change.get(
                "variant_title"
            )
            or "Unknown variant"
        )

        return (
            f"{product_title} / "
            f"{variant_title}"
        )

    def _display_value(
        self,
        value,
    ) -> str:
        """
        Convert missing values to a readable N/A.
        """

        if value is None:
            return "N/A"

        return str(value)

    def _money_value(
        self,
        value,
        currency_code: str,
    ) -> str:
        """
        Format already-calculated money text with
        its currency code.
        """

        if value is None:
            return "N/A"

        return (
            f"{value} "
            f"{currency_code}"
        )

    def _percent_value(
        self,
        value,
    ) -> str:
        """
        Format percentage text.
        """

        if value is None:
            return "N/A"

        return f"{value}%"
