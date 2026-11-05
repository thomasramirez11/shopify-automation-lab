from types import SimpleNamespace

import application.bootstrap as bootstrap


class FactoryRecorder:
    """
    Small test double that records constructor calls and returns
    unique objects carrying the received arguments.
    """

    def __init__(self, name):
        self.name = name
        self.calls = []

    def __call__(self, *args, **kwargs):
        instance = SimpleNamespace(
            factory=self.name,
            args=args,
            kwargs=kwargs,
        )

        self.calls.append(
            instance
        )

        return instance


def replace_factory(
    monkeypatch,
    name,
):
    recorder = FactoryRecorder(
        name
    )

    monkeypatch.setattr(
        bootstrap,
        name,
        recorder,
    )

    return recorder


def test_failure_dependencies_use_one_alert_repository(
    monkeypatch,
):
    sync_factory = replace_factory(
        monkeypatch,
        "SyncRunRepository",
    )

    alert_repo_factory = replace_factory(
        monkeypatch,
        "AlertRepository",
    )

    alert_service_factory = replace_factory(
        monkeypatch,
        "AlertService",
    )

    dependencies = (
        bootstrap
        .build_failure_safe_dependencies()
    )

    assert dependencies.sync_run_repository is (
        sync_factory.calls[0]
    )

    assert dependencies.alert_repository is (
        alert_repo_factory.calls[0]
    )

    assert dependencies.alert_service is (
        alert_service_factory.calls[0]
    )

    assert (
        dependencies
        .alert_service
        .kwargs["alert_repository"]
        is dependencies.alert_repository
    )


def test_shopify_client_uses_configured_credentials(
    monkeypatch,
):
    client_factory = replace_factory(
        monkeypatch,
        "ShopifyClient",
    )

    client = (
        bootstrap
        .build_shopify_client()
    )

    assert client is client_factory.calls[0]

    assert client.kwargs == {
        "store_domain":
            bootstrap.SHOPIFY_STORE_DOMAIN,
        "client_id":
            bootstrap.SHOPIFY_CLIENT_ID,
        "client_secret":
            bootstrap.SHOPIFY_CLIENT_SECRET,
        "api_version":
            bootstrap.SHOPIFY_API_VERSION,
    }


def test_core_services_share_supplied_shopify_client(
    monkeypatch,
):
    product_service_factory = replace_factory(
        monkeypatch,
        "ProductService",
    )

    order_service_factory = replace_factory(
        monkeypatch,
        "OrderService",
    )

    for name in (
        "ProfitService",
        "ProductRepository",
        "OrderRepository",
        "CostRepository",
        "ProfitSnapshotRepository",
        "FinancialProcessingService",
    ):
        replace_factory(
            monkeypatch,
            name,
        )

    client = object()

    dependencies = (
        bootstrap
        .build_core_dependencies(
            client=client,
        )
    )

    assert (
        product_service_factory.calls[0]
        .args
        == (client,)
    )

    assert (
        order_service_factory.calls[0]
        .args
        == (client,)
    )

    assert dependencies.product_service is (
        product_service_factory.calls[0]
    )

    assert dependencies.order_service is (
        order_service_factory.calls[0]
    )


def test_core_dependencies_expose_runtime_repositories(
    monkeypatch,
):
    factories = {}

    for name in (
        "ProductService",
        "OrderService",
        "ProfitService",
        "ProductRepository",
        "OrderRepository",
        "CostRepository",
        "ProfitSnapshotRepository",
        "FinancialProcessingService",
    ):
        factories[name] = replace_factory(
            monkeypatch,
            name,
        )

    dependencies = (
        bootstrap
        .build_core_dependencies(
            client=object(),
        )
    )

    assert dependencies.product_repository is (
        factories["ProductRepository"].calls[0]
    )

    assert dependencies.order_repository is (
        factories["OrderRepository"].calls[0]
    )

    assert (
        dependencies
        .profit_snapshot_repository
        is factories[
            "ProfitSnapshotRepository"
        ].calls[0]
    )


def test_financial_service_receives_internal_dependencies(
    monkeypatch,
):
    factories = {}

    for name in (
        "ProductService",
        "OrderService",
        "ProfitService",
        "ProductRepository",
        "OrderRepository",
        "CostRepository",
        "ProfitSnapshotRepository",
        "FinancialProcessingService",
    ):
        factories[name] = replace_factory(
            monkeypatch,
            name,
        )

    dependencies = (
        bootstrap
        .build_core_dependencies(
            client=object(),
        )
    )

    financial_service = factories[
        "FinancialProcessingService"
    ].calls[0]

    assert (
        financial_service.kwargs[
            "order_repository"
        ]
        is dependencies.order_repository
    )

    assert (
        financial_service.kwargs[
            "cost_repository"
        ]
        is factories[
            "CostRepository"
        ].calls[0]
    )

    assert (
        financial_service.kwargs[
            "snapshot_repository"
        ]
        is (
            dependencies
            .profit_snapshot_repository
        )
    )

    assert (
        financial_service.kwargs[
            "profit_service"
        ]
        is factories[
            "ProfitService"
        ].calls[0]
    )


def test_reporting_uses_existing_runtime_repositories(
    monkeypatch,
):
    report_factory = replace_factory(
        monkeypatch,
        "ReportService",
    )

    replace_factory(
        monkeypatch,
        "TerminalReportFormatter",
    )

    replace_factory(
        monkeypatch,
        "DailyReportRepository",
    )

    replace_factory(
        monkeypatch,
        "DailyReportService",
    )

    product_repository = object()
    order_repository = object()
    alert_repository = object()
    sync_run_repository = object()
    snapshot_repository = object()

    bootstrap.build_daily_report_service(
        product_repository=(
            product_repository
        ),
        order_repository=order_repository,
        alert_repository=alert_repository,
        sync_run_repository=(
            sync_run_repository
        ),
        profit_snapshot_repository=(
            snapshot_repository
        ),
    )

    kwargs = report_factory.calls[0].kwargs

    assert kwargs[
        "product_repository"
    ] is product_repository

    assert kwargs[
        "order_repository"
    ] is order_repository

    assert kwargs[
        "alert_repository"
    ] is alert_repository

    assert kwargs[
        "sync_run_repository"
    ] is sync_run_repository

    assert kwargs[
        "profit_snapshot_repository"
    ] is snapshot_repository


def test_reporting_preserves_report_configuration(
    monkeypatch,
):
    report_factory = replace_factory(
        monkeypatch,
        "ReportService",
    )

    formatter_factory = replace_factory(
        monkeypatch,
        "TerminalReportFormatter",
    )

    for name in (
        "DailyReportRepository",
        "DailyReportService",
    ):
        replace_factory(
            monkeypatch,
            name,
        )

    bootstrap.build_daily_report_service(
        product_repository=object(),
        order_repository=object(),
        alert_repository=object(),
        sync_run_repository=object(),
        profit_snapshot_repository=object(),
    )

    assert (
        report_factory.calls[0]
        .kwargs["low_inventory_threshold"]
        == bootstrap.LOW_INVENTORY_THRESHOLD
    )

    assert (
        report_factory.calls[0]
        .kwargs["recent_change_limit"]
        == bootstrap.REPORT_RECENT_CHANGE_LIMIT
    )

    assert (
        formatter_factory.calls[0]
        .kwargs["recent_changes_to_show"]
        == (
            bootstrap
            .TERMINAL_RECENT_CHANGES_TO_SHOW
        )
    )


def test_daily_report_service_receives_reporting_components(
    monkeypatch,
):
    report_factory = replace_factory(
        monkeypatch,
        "ReportService",
    )

    formatter_factory = replace_factory(
        monkeypatch,
        "TerminalReportFormatter",
    )

    repository_factory = replace_factory(
        monkeypatch,
        "DailyReportRepository",
    )

    service_factory = replace_factory(
        monkeypatch,
        "DailyReportService",
    )

    service = (
        bootstrap
        .build_daily_report_service(
            product_repository=object(),
            order_repository=object(),
            alert_repository=object(),
            sync_run_repository=object(),
            profit_snapshot_repository=object(),
        )
    )

    assert service is service_factory.calls[0]

    assert (
        service.kwargs["report_service"]
        is report_factory.calls[0]
    )

    assert (
        service.kwargs["report_formatter"]
        is formatter_factory.calls[0]
    )

    assert (
        service.kwargs[
            "daily_report_repository"
        ]
        is repository_factory.calls[0]
    )
