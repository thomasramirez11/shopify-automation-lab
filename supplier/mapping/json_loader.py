from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from supplier.mapping.memory_registry import (
    InMemorySupplierMappingRegistry,
)
from supplier.mapping.models import (
    SupplierMappingError,
    SupplierVariantMapping,
)


class SupplierMappingFeedError(
    SupplierMappingError
):
    """
    Raised when an explicit mapping feed cannot be trusted or normalized.
    """


class JsonSupplierMappingLoader:
    """
    Load explicit supplier-to-Shopify mappings from a JSON file.

    This loader only creates mapping objects. It does not contact Shopify
    and cannot modify Shopify inventory, prices, products, or orders.
    """

    def __init__(
        self,
        mapping_path: str | Path,
    ) -> None:
        self._mapping_path = Path(
            mapping_path
        )

    def load_mappings(
        self,
    ) -> tuple[
        SupplierVariantMapping,
        ...,
    ]:
        """
        Parse and normalize all mappings from the configured JSON file.
        """

        rows = self._load_rows()

        mappings: list[
            SupplierVariantMapping
        ] = []

        for row_number, row in enumerate(
            rows,
            start=1,
        ):
            mappings.append(
                self._normalize_row(
                    row,
                    row_number=row_number,
                )
            )

        return tuple(
            mappings
        )

    def load_registry(
        self,
    ) -> InMemorySupplierMappingRegistry:
        """
        Build the conflict-detecting V2 mapping registry.
        """

        try:
            return (
                InMemorySupplierMappingRegistry(
                    self.load_mappings()
                )
            )

        except SupplierMappingError as exc:
            raise SupplierMappingFeedError(
                "Supplier mapping feed contains "
                f"conflicting mappings: {exc}"
            ) from exc

    def _load_rows(
        self,
    ) -> list[Any]:
        if not self._mapping_path.is_file():
            raise SupplierMappingFeedError(
                "Supplier mapping file does not exist: "
                f"{self._mapping_path}"
            )

        try:
            raw_text = (
                self._mapping_path.read_text(
                    encoding="utf-8"
                )
            )

            payload = json.loads(
                raw_text
            )

        except UnicodeDecodeError as exc:
            raise SupplierMappingFeedError(
                "Supplier mapping file must be UTF-8 encoded."
            ) from exc

        except json.JSONDecodeError as exc:
            raise SupplierMappingFeedError(
                "Supplier mapping file contains invalid JSON."
            ) from exc

        if not isinstance(
            payload,
            list,
        ):
            raise SupplierMappingFeedError(
                "Supplier mapping feed root must be a JSON array."
            )

        return payload

    def _normalize_row(
        self,
        raw_row: Any,
        *,
        row_number: int,
    ) -> SupplierVariantMapping:
        if not isinstance(
            raw_row,
            dict,
        ):
            raise SupplierMappingFeedError(
                f"Supplier mapping row {row_number} "
                "must be a JSON object."
            )

        required_fields = (
            "supplier_code",
            "supplier_sku",
            "shopify_variant_id",
            "shopify_sku",
        )

        missing_fields = [
            field_name
            for field_name
            in required_fields
            if field_name
            not in raw_row
        ]

        if missing_fields:
            raise SupplierMappingFeedError(
                f"Supplier mapping row {row_number} "
                "is missing required field(s): "
                + ", ".join(
                    missing_fields
                )
            )

        active = raw_row.get(
            "active",
            True,
        )

        try:
            return SupplierVariantMapping(
                supplier_code=(
                    raw_row[
                        "supplier_code"
                    ]
                ),
                supplier_sku=(
                    raw_row[
                        "supplier_sku"
                    ]
                ),
                shopify_variant_id=(
                    raw_row[
                        "shopify_variant_id"
                    ]
                ),
                shopify_sku=(
                    raw_row[
                        "shopify_sku"
                    ]
                ),
                active=active,
            )

        except SupplierMappingError as exc:
            raise SupplierMappingFeedError(
                f"Supplier mapping row {row_number} "
                f"is invalid: {exc}"
            ) from exc
