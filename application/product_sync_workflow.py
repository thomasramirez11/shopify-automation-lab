from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from application.presentation_ports import (
    SyncWorkflowPresenter,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductSyncState:
    """
    Product data retrieved from Shopify for the current sync run.

    The raw Shopify product structures are intentionally preserved
    because later inventory-alert processing still needs them.
    """

    products: list[dict]

    @property
    def products_seen(self) -> int:
        """
        Number of Shopify products retrieved.
        """

        return len(self.products)


@dataclass(frozen=True)
class ProductPersistenceSnapshot:
    """
    Database state used to verify Shopify product persistence.

    Reading this state is intentionally separate from verification so
    the top-level coordinator can preserve the existing execution order:
    product DB reads happen before order DB reads, while the product
    verification output still happens after both read phases.
    """

    stored_products: list[dict]
    stored_variants: list[dict]
    expected_variant_count: int


@dataclass(frozen=True)
class ProductVerificationResult:
    """
    Verified product counts returned to the sync coordinator.
    """

    products_seen: int
    variants_seen: int


def retrieve_products(
    *,
    product_service: Any,
    presenter: SyncWorkflowPresenter,
) -> ProductSyncState:
    """
    Retrieve Shopify products and present the retrieval result.
    """

    presenter.show_product_retrieval_started()

    products = (
        product_service
        .get_all_products()
    )

    logger.info(
        "Retrieved %s products from Shopify.",
        len(products),
    )

    presenter.show_product_retrieval_result(
        products
    )

    return ProductSyncState(
        products=products,
    )


def persist_products(
    *,
    product_state: ProductSyncState,
    product_repository: Any,
    presenter: SyncWorkflowPresenter,
) -> None:
    """
    Persist the current Shopify product snapshot to SQLite.
    """

    presenter.show_product_persistence_started()

    for product in product_state.products:
        product_repository.save_product(
            product
        )

    presenter.show_product_persistence_success()

    logger.info(
        "Product persistence completed. products=%s",
        product_state.products_seen,
    )


def read_product_persistence_state(
    *,
    product_state: ProductSyncState,
    product_repository: Any,
) -> ProductPersistenceSnapshot:
    """
    Read product/variant database state for later verification.

    This function intentionally performs no presentation. That keeps
    the existing sync-workflow output order unchanged.
    """

    stored_products = (
        product_repository
        .get_all_products()
    )

    stored_variants = (
        product_repository
        .get_all_variants()
    )

    expected_variant_count = sum(
        len(
            product[
                "variants"
            ][
                "edges"
            ]
        )
        for product in product_state.products
    )

    return ProductPersistenceSnapshot(
        stored_products=stored_products,
        stored_variants=stored_variants,
        expected_variant_count=(
            expected_variant_count
        ),
    )


def verify_product_persistence(
    *,
    product_state: ProductSyncState,
    persistence_snapshot: ProductPersistenceSnapshot,
    presenter: SyncWorkflowPresenter,
) -> ProductVerificationResult:
    """
    Verify that Shopify product/variant counts match SQLite state.

    Raises the same RuntimeError used by the original coordinator so
    existing synchronization failure semantics remain unchanged.
    """

    presenter.show_product_database_verification(
        shopify_products=(
            product_state.products_seen
        ),
        database_products=len(
            persistence_snapshot
            .stored_products
        ),
        shopify_variants=(
            persistence_snapshot
            .expected_variant_count
        ),
        database_variants=len(
            persistence_snapshot
            .stored_variants
        ),
    )

    products_match = (
        product_state.products_seen
        == len(
            persistence_snapshot
            .stored_products
        )
    )

    variants_match = (
        persistence_snapshot
        .expected_variant_count
        == len(
            persistence_snapshot
            .stored_variants
        )
    )

    if not (
        products_match
        and variants_match
    ):
        raise RuntimeError(
            "Shopify and SQLite product "
            "record counts do not match."
        )

    presenter.show_product_database_verification_success()

    return ProductVerificationResult(
        products_seen=(
            product_state.products_seen
        ),
        variants_seen=(
            persistence_snapshot
            .expected_variant_count
        ),
    )
