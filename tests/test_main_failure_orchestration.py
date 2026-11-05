import pytest

import main as app_main


class FakeSyncRunRepository:
    """
    In-memory test double for synchronization audit behavior.
    """

    def __init__(
        self,
        *,
        start_run_id=777,
        fail_on_start=False,
        fail_on_mark_failed=False,
    ):
        self.start_run_id = start_run_id
        self.fail_on_start = fail_on_start
        self.fail_on_mark_failed = (
            fail_on_mark_failed
        )

        self.start_calls = 0
        self.failed_calls = []

    def start_run(self):
        self.start_calls += 1

        if self.fail_on_start:
            raise RuntimeError(
                "audit start failed"
            )

        return self.start_run_id

    def mark_failed(
        self,
        *,
        run_id,
        error_message,
    ):
        self.failed_calls.append(
            {
                "run_id": run_id,
                "error_message": error_message,
            }
        )

        if self.fail_on_mark_failed:
            raise RuntimeError(
                "audit failure write failed"
            )


class FakeAlertRepository:
    """
    Placeholder dependency required by AlertService construction.
    """


class FakeAlertService:
    """
    In-memory test double for synchronization-failure alerts.
    """

    def __init__(
        self,
        alert_repository,
        *,
        fail_on_create=False,
    ):
        self.alert_repository = alert_repository
        self.fail_on_create = fail_on_create
        self.sync_failure_calls = []

    def create_sync_failure_alert(
        self,
        *,
        sync_run_id,
        error_type,
    ):
        self.sync_failure_calls.append(
            {
                "sync_run_id": sync_run_id,
                "error_type": error_type,
            }
        )

        if self.fail_on_create:
            raise RuntimeError(
                "failure alert write failed"
            )

        return {
            "id": 1,
            "alert_type": "sync_failure",
            "severity": "error",
            "status": "open",
        }


@pytest.fixture
def failure_environment(
    monkeypatch,
):
    """
    Enable the controlled failure hook and isolate logging.
    """

    monkeypatch.setenv(
        "SHOPIFY_AUTOMATION_TEST_SYNC_FAILURE",
        "1",
    )

    monkeypatch.setattr(
        app_main,
        "setup_logging",
        lambda: "test.log",
    )


def install_failure_doubles(
    monkeypatch,
    *,
    sync_repository,
    alert_service,
):
    """
    Replace the real database-backed dependencies with
    in-memory doubles.
    """

    monkeypatch.setattr(
        app_main,
        "SyncRunRepository",
        lambda: sync_repository,
    )

    monkeypatch.setattr(
        app_main,
        "AlertRepository",
        lambda: FakeAlertRepository(),
    )

    monkeypatch.setattr(
        app_main,
        "AlertService",
        lambda alert_repository: alert_service,
    )


def test_controlled_sync_failure_marks_audit_and_creates_alert(
    monkeypatch,
    failure_environment,
):
    sync_repository = (
        FakeSyncRunRepository(
            start_run_id=46,
        )
    )

    alert_service = FakeAlertService(
        FakeAlertRepository()
    )

    install_failure_doubles(
        monkeypatch,
        sync_repository=sync_repository,
        alert_service=alert_service,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Intentional Stage 6.8 "
            "synchronization failure test"
        ),
    ):
        app_main.main()

    assert sync_repository.start_calls == 1

    assert sync_repository.failed_calls == [
        {
            "run_id": 46,
            "error_message": (
                "RuntimeError: "
                "Intentional Stage 6.8 "
                "synchronization failure test"
            ),
        }
    ]

    assert alert_service.sync_failure_calls == [
        {
            "sync_run_id": 46,
            "error_type": "RuntimeError",
        }
    ]


def test_failure_hook_stops_before_shopify_client_creation(
    monkeypatch,
    failure_environment,
):
    sync_repository = FakeSyncRunRepository()

    alert_service = FakeAlertService(
        FakeAlertRepository()
    )

    install_failure_doubles(
        monkeypatch,
        sync_repository=sync_repository,
        alert_service=alert_service,
    )

    class ShopifyClientMustNotBeCreated:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "ShopifyClient should not be created "
                "after the controlled failure hook."
            )

    monkeypatch.setattr(
        app_main,
        "ShopifyClient",
        ShopifyClientMustNotBeCreated,
    )

    with pytest.raises(
        RuntimeError,
        match="Intentional Stage 6.8",
    ):
        app_main.main()


def test_audit_failure_does_not_hide_original_sync_error(
    monkeypatch,
    failure_environment,
):
    sync_repository = FakeSyncRunRepository(
        fail_on_mark_failed=True,
    )

    alert_service = FakeAlertService(
        FakeAlertRepository()
    )

    install_failure_doubles(
        monkeypatch,
        sync_repository=sync_repository,
        alert_service=alert_service,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Intentional Stage 6.8 "
            "synchronization failure test"
        ),
    ):
        app_main.main()

    assert len(
        sync_repository.failed_calls
    ) == 1

    # Even though audit persistence failed, the alert path
    # still gets a chance to run.
    assert len(
        alert_service.sync_failure_calls
    ) == 1


def test_failure_alert_error_does_not_hide_original_sync_error(
    monkeypatch,
    failure_environment,
):
    sync_repository = FakeSyncRunRepository()

    alert_service = FakeAlertService(
        FakeAlertRepository(),
        fail_on_create=True,
    )

    install_failure_doubles(
        monkeypatch,
        sync_repository=sync_repository,
        alert_service=alert_service,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Intentional Stage 6.8 "
            "synchronization failure test"
        ),
    ):
        app_main.main()

    assert len(
        sync_repository.failed_calls
    ) == 1

    assert len(
        alert_service.sync_failure_calls
    ) == 1


def test_both_secondary_failures_still_preserve_original_error(
    monkeypatch,
    failure_environment,
):
    sync_repository = FakeSyncRunRepository(
        fail_on_mark_failed=True,
    )

    alert_service = FakeAlertService(
        FakeAlertRepository(),
        fail_on_create=True,
    )

    install_failure_doubles(
        monkeypatch,
        sync_repository=sync_repository,
        alert_service=alert_service,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Intentional Stage 6.8 "
            "synchronization failure test"
        ),
    ):
        app_main.main()

    assert len(
        sync_repository.failed_calls
    ) == 1

    assert len(
        alert_service.sync_failure_calls
    ) == 1


def test_start_run_failure_propagates_without_secondary_audit_work(
    monkeypatch,
    failure_environment,
):
    sync_repository = FakeSyncRunRepository(
        fail_on_start=True,
    )

    alert_service = FakeAlertService(
        FakeAlertRepository()
    )

    install_failure_doubles(
        monkeypatch,
        sync_repository=sync_repository,
        alert_service=alert_service,
    )

    with pytest.raises(
        RuntimeError,
        match="audit start failed",
    ):
        app_main.main()

    # No audit ID exists yet, so there is nothing to mark
    # failed and no sync-failure alert should be generated.
    assert sync_repository.failed_calls == []
    assert alert_service.sync_failure_calls == []
