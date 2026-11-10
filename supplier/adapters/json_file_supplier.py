from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from supplier.models import (
    SupplierDataError,
    SupplierProduct,
)


class SupplierFeedError(SupplierDataError):
    """
    Raised when a supplier JSON feed cannot be trusted or normalized.
    """


class JsonFileSupplierAdapter:
    """
    Read-only supplier adapter backed by a JSON file.

    Expected feed shape:

    [
        {
            "sku": "SUP-CAP-001",
            "name": "Automation Test Cap",
            "available": 25,
            "cost": "4.25",
            "currency": "USD",
            "updated_at": "2026-11-10T21:00:00Z"
        }
    ]

    This adapter does not contact Shopify and cannot modify Shopify.
    """

    def __init__(
        self,
        feed_path: str | Path,
    ) -> None:
        self._feed_path = Path(
            feed_path
        )

    def list_products(
        self,
    ) -> tuple[SupplierProduct, ...]:
        """
        Load, validate, normalize, and return the full supplier catalog.
        """

        raw_records = (
            self._load_raw_records()
        )

        products: list[
            SupplierProduct
        ] = []

        seen_skus: set[str] = set()

        for index, raw_record in enumerate(
            raw_records,
            start=1,
        ):
            product = (
                self._normalize_record(
                    raw_record,
                    row_number=index,
                )
            )

            if (
                product.supplier_sku
                in seen_skus
            ):
                raise SupplierFeedError(
                    "Duplicate supplier SKU "
                    f"'{product.supplier_sku}' "
                    f"found at row {index}."
                )

            seen_skus.add(
                product.supplier_sku
            )

            products.append(
                product
            )

        return tuple(
            products
        )

    def get_product_by_sku(
        self,
        supplier_sku: str,
    ) -> SupplierProduct | None:
        """
        Return one normalized supplier product when present.
        """

        normalized_sku = (
            supplier_sku.strip()
        )

        for product in (
            self.list_products()
        ):
            if (
                product.supplier_sku
                == normalized_sku
            ):
                return product

        return None

    def _load_raw_records(
        self,
    ) -> list[Any]:
        """
        Read the supplier JSON feed without executing external code.
        """

        if not self._feed_path.is_file():
            raise SupplierFeedError(
                "Supplier feed file does not exist: "
                f"{self._feed_path}"
            )

        try:
            raw_text = (
                self._feed_path.read_text(
                    encoding="utf-8"
                )
            )

            payload = json.loads(
                raw_text
            )

        except UnicodeDecodeError as exc:
            raise SupplierFeedError(
                "Supplier feed must be UTF-8 encoded."
            ) from exc

        except json.JSONDecodeError as exc:
            raise SupplierFeedError(
                "Supplier feed contains invalid JSON."
            ) from exc

        if not isinstance(
            payload,
            list,
        ):
            raise SupplierFeedError(
                "Supplier feed root must be a JSON array."
            )

        return payload

    def _normalize_record(
        self,
        raw_record: Any,
        *,
        row_number: int,
    ) -> SupplierProduct:
        """
        Convert one supplier-specific record into SupplierProduct.
        """

        if not isinstance(
            raw_record,
            dict,
        ):
            raise SupplierFeedError(
                f"Supplier feed row {row_number} "
                "must be a JSON object."
            )

        required_fields = (
            "sku",
            "name",
            "available",
            "cost",
            "currency",
            "updated_at",
        )

        missing_fields = [
            field_name
            for field_name
            in required_fields
            if field_name
            not in raw_record
        ]

        if missing_fields:
            raise SupplierFeedError(
                f"Supplier feed row {row_number} "
                "is missing required field(s): "
                + ", ".join(
                    missing_fields
                )
            )

        source_updated_at = (
            self._parse_timestamp(
                raw_record[
                    "updated_at"
                ],
                row_number=row_number,
            )
        )

        try:
            return SupplierProduct(
                supplier_sku=(
                    raw_record["sku"]
                ),
                title=(
                    raw_record["name"]
                ),
                stock_quantity=(
                    raw_record[
                        "available"
                    ]
                ),
                unit_cost=(
                    raw_record["cost"]
                ),
                currency=(
                    raw_record[
                        "currency"
                    ]
                ),
                source_updated_at=(
                    source_updated_at
                ),
            )

        except SupplierDataError as exc:
            raise SupplierFeedError(
                f"Supplier feed row {row_number} "
                f"is invalid: {exc}"
            ) from exc

    def _parse_timestamp(
        self,
        raw_value: Any,
        *,
        row_number: int,
    ) -> datetime:
        """
        Parse ISO-8601 supplier timestamps and require timezone data.
        """

        if not isinstance(
            raw_value,
            str,
        ):
            raise SupplierFeedError(
                f"Supplier feed row {row_number} "
                "updated_at must be a string."
            )

        normalized = (
            raw_value.strip()
        )

        if normalized.endswith(
            "Z"
        ):
            normalized = (
                normalized[:-1]
                + "+00:00"
            )

        try:
            parsed = (
                datetime.fromisoformat(
                    normalized
                )
            )

        except ValueError as exc:
            raise SupplierFeedError(
                f"Supplier feed row {row_number} "
                "updated_at must be valid ISO-8601."
            ) from exc

        if (
            parsed.tzinfo is None
            or parsed.utcoffset()
            is None
        ):
            raise SupplierFeedError(
                f"Supplier feed row {row_number} "
                "updated_at must include timezone information."
            )

        return parsed
