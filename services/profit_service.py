from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_UP,
)


class ProfitService:
    """
    Handles financial calculations for Shopify orders
    and order line items.

    All monetary calculations use Decimal instead of float.
    """

    MONEY_QUANTIZER = Decimal("0.01")
    PERCENT_QUANTIZER = Decimal("0.01")

    def calculate_line_item_profit(
        self,
        unit_sale_price,
        unit_cost,
        quantity: int,
        sale_currency: str,
        cost_currency: str,
    ) -> dict:
        """
        Calculate estimated gross profit for one order line item.

        Returns normalized string values suitable for
        persistence in SQLite.
        """

        sale_price = self._to_decimal(
            unit_sale_price,
            field_name="unit_sale_price",
        )

        cost = self._to_decimal(
            unit_cost,
            field_name="unit_cost",
        )

        normalized_quantity = self._validate_quantity(
            quantity
        )

        normalized_sale_currency = (
            self._normalize_currency(
                sale_currency,
                field_name="sale_currency",
            )
        )

        normalized_cost_currency = (
            self._normalize_currency(
                cost_currency,
                field_name="cost_currency",
            )
        )

        if (
            normalized_sale_currency
            != normalized_cost_currency
        ):
            raise ValueError(
                "Cannot calculate profit across "
                "different currencies without "
                "currency conversion."
            )

        line_revenue = (
            sale_price
            * normalized_quantity
        )

        line_cost = (
            cost
            * normalized_quantity
        )

        estimated_gross_profit = (
            line_revenue
            - line_cost
        )

        gross_margin_percent = None

        if line_revenue > 0:
            gross_margin_percent = (
                estimated_gross_profit
                / line_revenue
                * Decimal("100")
            )

        return {
            "currency_code":
                normalized_sale_currency,

            "quantity":
                normalized_quantity,

            "unit_sale_price":
                self._format_money(
                    sale_price
                ),

            "unit_cost":
                self._format_money(
                    cost
                ),

            "line_revenue":
                self._format_money(
                    line_revenue
                ),

            "line_cost":
                self._format_money(
                    line_cost
                ),

            "estimated_gross_profit":
                self._format_money(
                    estimated_gross_profit
                ),

            "gross_margin_percent":
                (
                    self._format_percent(
                        gross_margin_percent
                    )
                    if gross_margin_percent
                    is not None
                    else None
                ),
        }

    def calculate_order_summary(
        self,
        snapshots: list,
    ) -> dict:
        """
        Aggregate multiple line-item profit snapshots
        into one order-level financial summary.

        All snapshots must use the same currency.
        """

        if not snapshots:
            raise ValueError(
                "At least one profit snapshot "
                "is required."
            )

        currencies = {
            self._normalize_currency(
                snapshot["currency_code"],
                field_name="currency_code",
            )
            for snapshot in snapshots
        }

        if len(currencies) != 1:
            raise ValueError(
                "Cannot summarize snapshots "
                "with different currencies."
            )

        currency_code = currencies.pop()

        total_revenue = Decimal("0")
        total_cost = Decimal("0")
        total_profit = Decimal("0")
        total_quantity = 0

        for snapshot in snapshots:
            total_revenue += self._to_decimal(
                snapshot["line_revenue"],
                field_name="line_revenue",
            )

            total_cost += self._to_decimal(
                snapshot["line_cost"],
                field_name="line_cost",
            )

            total_profit += self._to_decimal(
                snapshot[
                    "estimated_gross_profit"
                ],
                field_name=(
                    "estimated_gross_profit"
                ),
            )

            total_quantity += (
                self._validate_quantity(
                    snapshot["quantity"]
                )
            )

        gross_margin_percent = None

        if total_revenue > 0:
            gross_margin_percent = (
                total_profit
                / total_revenue
                * Decimal("100")
            )

        return {
            "currency_code":
                currency_code,

            "line_items_count":
                len(snapshots),

            "total_quantity":
                total_quantity,

            "merchandise_revenue":
                self._format_money(
                    total_revenue
                ),

            "product_cost":
                self._format_money(
                    total_cost
                ),

            "estimated_gross_profit":
                self._format_money(
                    total_profit
                ),

            "gross_margin_percent":
                (
                    self._format_percent(
                        gross_margin_percent
                    )
                    if gross_margin_percent
                    is not None
                    else None
                ),
        }

    def _to_decimal(
        self,
        value,
        field_name: str,
    ) -> Decimal:
        """
        Convert and validate one monetary value.
        """

        try:
            decimal_value = Decimal(
                str(value)
            )
        except (
            InvalidOperation,
            ValueError,
            TypeError,
        ) as exc:
            raise ValueError(
                f"{field_name} must be "
                "a valid decimal number."
            ) from exc

        if decimal_value < 0:
            raise ValueError(
                f"{field_name} cannot be negative."
            )

        return decimal_value

    def _validate_quantity(
        self,
        quantity,
    ) -> int:
        """
        Validate a quantity.
        """

        if isinstance(quantity, bool):
            raise ValueError(
                "quantity must be an integer."
            )

        if not isinstance(quantity, int):
            raise ValueError(
                "quantity must be an integer."
            )

        if quantity < 0:
            raise ValueError(
                "quantity cannot be negative."
            )

        return quantity

    def _normalize_currency(
        self,
        currency_code: str,
        field_name: str,
    ) -> str:
        """
        Validate and normalize a currency code.
        """

        if not isinstance(
            currency_code,
            str,
        ):
            raise ValueError(
                f"{field_name} must be a string."
            )

        normalized_currency = (
            currency_code.strip().upper()
        )

        if not normalized_currency:
            raise ValueError(
                f"{field_name} is required."
            )

        return normalized_currency

    def _format_money(
        self,
        value: Decimal,
    ) -> str:
        """
        Round monetary values to two decimal places.
        """

        rounded_value = value.quantize(
            self.MONEY_QUANTIZER,
            rounding=ROUND_HALF_UP,
        )

        return format(
            rounded_value,
            ".2f",
        )

    def _format_percent(
        self,
        value: Decimal,
    ) -> str:
        """
        Round percentages to two decimal places.
        """

        rounded_value = value.quantize(
            self.PERCENT_QUANTIZER,
            rounding=ROUND_HALF_UP,
        )

        return format(
            rounded_value,
            ".2f",
        )