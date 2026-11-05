import pytest

from application.product_sync_workflow import (
    ProductPersistenceSnapshot,
    ProductSyncState,
    persist_products,
    read_product_persistence_state,
    retrieve_products,
    verify_product_persistence,
)


class RecordingPresenter:
    def __init__(self):
        self.calls = []

    def show_product_retrieval_started(self):
        self.calls.append(
            (
                "retrieval_started",
                None,
            )
        )

    def show_product_retrieval_result(
        self,
        products,
    ):
        self.calls.append(
            (
                "retrieval_result",
                products,
            )
        )

    def show_product_persistence_started(self):
        self.calls.append(
            (
                "persistence_started",
                None,
            )
        )

    def show_product_persistence_success(self):
        self.calls.append(
            (
                "persistence_success",
                None,
            )
        )

    def show_product_database_verification(
        self,
        **kwargs,
    ):
        self.calls.append(
            (
                "verification",
                kwargs,
            )
        )

    def show_product_database_verification_success(
        self,
    ):
        self.calls.append(
            (
                "verification_success",
                None,
            )
        )


class FakeProductService:
    def __init__(
        self,
        *,
        products=None,
        error=None,
    ):
        self.products = (
            products
            if products is not None
            else []
        )
        self.error = error
        self.calls = 0

    def get_all_products(self):
        self.calls += 1

        if self.error is not None:
            raise self.error

        return self.products


class FakeProductRepository:
    def __init__(
        self,
        *,
        stored_products=None,
        stored_variants=None,
        fail_on_save_index=None,
    ):
        self.saved_products = []

        self.stored_products = (
            stored_products
            if stored_products is not None
            else []
        )

        self.stored_variants = (
            stored_variants
            if stored_variants is not None
            else []
        )

        self.fail_on_save_index = (
            fail_on_save_index
        )

    def save_product(
        self,
        product,
    ):
        if (
            self.fail_on_save_index
            is not None
            and len(
                self.saved_products
            )
            == self.fail_on_save_index
        ):
            raise RuntimeError(
                "save failed"
            )

        self.saved_products.append(
            product
        )

    def get_all_products(self):
        return self.stored_products

    def get_all_variants(self):
        return self.stored_variants


def make_product(
    *,
    product_id,
    variant_count,
):
    return {
        "id": product_id,
        "variants": {
            "edges": [
                {
                    "node": {
                        "id": (
                            f"{product_id}-"
                            f"variant-{index}"
                        )
                    }
                }
                for index in range(
                    variant_count
                )
            ]
        },
    }


def test_retrieve_products_returns_state_and_preserves_output_order():
    products = [
        make_product(
            product_id="product-1",
            variant_count=1,
        )
    ]

    presenter = RecordingPresenter()

    service = FakeProductService(
        products=products,
    )

    result = retrieve_products(
        product_service=service,
        presenter=presenter,
    )

    assert isinstance(
        result,
        ProductSyncState,
    )

    assert result.products is products
    assert result.products_seen == 1
    assert service.calls == 1

    assert presenter.calls == [
        (
            "retrieval_started",
            None,
        ),
        (
            "retrieval_result",
            products,
        ),
    ]


def test_retrieve_products_propagates_service_failure_without_success_output():
    presenter = RecordingPresenter()

    with pytest.raises(
        RuntimeError,
        match="Shopify unavailable",
    ):
        retrieve_products(
            product_service=(
                FakeProductService(
                    error=RuntimeError(
                        "Shopify unavailable"
                    )
                )
            ),
            presenter=presenter,
        )

    assert presenter.calls == [
        (
            "retrieval_started",
            None,
        )
    ]


def test_persist_products_saves_every_product():
    products = [
        make_product(
            product_id="product-1",
            variant_count=1,
        ),
        make_product(
            product_id="product-2",
            variant_count=2,
        ),
    ]

    presenter = RecordingPresenter()
    repository = FakeProductRepository()

    persist_products(
        product_state=(
            ProductSyncState(
                products=products,
            )
        ),
        product_repository=repository,
        presenter=presenter,
    )

    assert (
        repository.saved_products
        == products
    )

    assert presenter.calls == [
        (
            "persistence_started",
            None,
        ),
        (
            "persistence_success",
            None,
        ),
    ]


def test_persist_products_does_not_report_success_after_repository_failure():
    products = [
        make_product(
            product_id="product-1",
            variant_count=1,
        ),
        make_product(
            product_id="product-2",
            variant_count=1,
        ),
    ]

    presenter = RecordingPresenter()

    repository = FakeProductRepository(
        fail_on_save_index=1,
    )

    with pytest.raises(
        RuntimeError,
        match="save failed",
    ):
        persist_products(
            product_state=(
                ProductSyncState(
                    products=products,
                )
            ),
            product_repository=repository,
            presenter=presenter,
        )

    assert presenter.calls == [
        (
            "persistence_started",
            None,
        )
    ]


def test_read_product_persistence_state_counts_expected_variants():
    products = [
        make_product(
            product_id="product-1",
            variant_count=1,
        ),
        make_product(
            product_id="product-2",
            variant_count=3,
        ),
    ]

    stored_products = [
        {"shopify_product_id": "1"},
        {"shopify_product_id": "2"},
    ]

    stored_variants = [
        {"shopify_variant_id": str(index)}
        for index in range(4)
    ]

    snapshot = (
        read_product_persistence_state(
            product_state=(
                ProductSyncState(
                    products=products,
                )
            ),
            product_repository=(
                FakeProductRepository(
                    stored_products=(
                        stored_products
                    ),
                    stored_variants=(
                        stored_variants
                    ),
                )
            ),
        )
    )

    assert isinstance(
        snapshot,
        ProductPersistenceSnapshot,
    )

    assert (
        snapshot.stored_products
        is stored_products
    )

    assert (
        snapshot.stored_variants
        is stored_variants
    )

    assert (
        snapshot.expected_variant_count
        == 4
    )


def test_verify_product_persistence_returns_verified_counts():
    presenter = RecordingPresenter()

    result = verify_product_persistence(
        product_state=(
            ProductSyncState(
                products=[
                    make_product(
                        product_id="product-1",
                        variant_count=2,
                    )
                ]
            )
        ),
        persistence_snapshot=(
            ProductPersistenceSnapshot(
                stored_products=[
                    {"id": "product-1"},
                ],
                stored_variants=[
                    {"id": "variant-1"},
                    {"id": "variant-2"},
                ],
                expected_variant_count=2,
            )
        ),
        presenter=presenter,
    )

    assert result.products_seen == 1
    assert result.variants_seen == 2

    assert presenter.calls[-1] == (
        "verification_success",
        None,
    )


def test_verify_product_persistence_rejects_product_count_mismatch():
    presenter = RecordingPresenter()

    with pytest.raises(
        RuntimeError,
        match=(
            "Shopify and SQLite product "
            "record counts do not match"
        ),
    ):
        verify_product_persistence(
            product_state=(
                ProductSyncState(
                    products=[
                        make_product(
                            product_id="product-1",
                            variant_count=1,
                        )
                    ]
                )
            ),
            persistence_snapshot=(
                ProductPersistenceSnapshot(
                    stored_products=[],
                    stored_variants=[
                        {"id": "variant-1"},
                    ],
                    expected_variant_count=1,
                )
            ),
            presenter=presenter,
        )

    assert (
        "verification_success",
        None,
    ) not in presenter.calls


def test_verify_product_persistence_rejects_variant_count_mismatch():
    presenter = RecordingPresenter()

    with pytest.raises(
        RuntimeError,
        match=(
            "Shopify and SQLite product "
            "record counts do not match"
        ),
    ):
        verify_product_persistence(
            product_state=(
                ProductSyncState(
                    products=[
                        make_product(
                            product_id="product-1",
                            variant_count=2,
                        )
                    ]
                )
            ),
            persistence_snapshot=(
                ProductPersistenceSnapshot(
                    stored_products=[
                        {"id": "product-1"},
                    ],
                    stored_variants=[
                        {"id": "variant-1"},
                    ],
                    expected_variant_count=2,
                )
            ),
            presenter=presenter,
        )

    assert (
        "verification_success",
        None,
    ) not in presenter.calls
