import application.failure_handler as failure_handler


class FakeSyncRunRepository:
    def __init__(
        self,
        *,
        fail_mark_failed=False,
    ):
        self.fail_mark_failed = (
            fail_mark_failed
        )
        self.calls = []

    def mark_failed(
        self,
        *,
        run_id,
        error_message,
    ):
        self.calls.append(
            {
                "run_id": run_id,
                "error_message": error_message,
            }
        )

        if self.fail_mark_failed:
            raise RuntimeError(
                "audit write failed"
            )


class FakeAlertService:
    def __init__(
        self,
        *,
        fail_alert=False,
    ):
        self.fail_alert = fail_alert
        self.calls = []

    def create_sync_failure_alert(
        self,
        *,
        sync_run_id,
        error_type,
    ):
        self.calls.append(
            {
                "sync_run_id": sync_run_id,
                "error_type": error_type,
            }
        )

        if self.fail_alert:
            raise RuntimeError(
                "alert write failed"
            )

        return {
            "id": 11,
            "alert_type": "sync_failure",
            "severity": "error",
            "status": "open",
        }


class RecordingFailurePresenter:
    def __init__(self):
        self.calls = []

    def show_sync_failure(
        self,
        **kwargs,
    ):
        self.calls.append(kwargs)


def make_failure_presenter():
    return RecordingFailurePresenter()


def test_failure_handler_marks_audit_and_creates_alert(
    monkeypatch,
):
    presenter = make_failure_presenter()

    sync_repository = (
        FakeSyncRunRepository()
    )

    alert_service = FakeAlertService()

    error = RuntimeError(
        "primary sync failure"
    )

    result = (
        failure_handler
        .handle_synchronization_failure(
            error=error,
            sync_run_id=46,
            sync_run_repository=(
                sync_repository
            ),
            alert_service=alert_service,
            presenter=presenter,
        )
    )

    assert result.error_type == "RuntimeError"

    assert result.error_message == (
        "RuntimeError: primary sync failure"
    )

    assert result.sync_run_marked_failed is True

    assert result.failure_alert["id"] == 11

    assert sync_repository.calls == [
        {
            "run_id": 46,
            "error_message": (
                "RuntimeError: "
                "primary sync failure"
            ),
        }
    ]

    assert alert_service.calls == [
        {
            "sync_run_id": 46,
            "error_type": "RuntimeError",
        }
    ]

    assert presenter.calls[0][
        "sync_run_marked_failed"
    ] is True


def test_audit_secondary_failure_does_not_stop_alert_creation(
    monkeypatch,
):
    presenter = make_failure_presenter()

    sync_repository = (
        FakeSyncRunRepository(
            fail_mark_failed=True,
        )
    )

    alert_service = FakeAlertService()

    result = (
        failure_handler
        .handle_synchronization_failure(
            error=ValueError("bad data"),
            sync_run_id=47,
            sync_run_repository=(
                sync_repository
            ),
            alert_service=alert_service,
            presenter=presenter,
        )
    )

    assert (
        result.sync_run_marked_failed
        is False
    )

    assert result.failure_alert["id"] == 11

    assert len(alert_service.calls) == 1

    assert presenter.calls[0][
        "sync_run_marked_failed"
    ] is False


def test_alert_secondary_failure_does_not_hide_audit_result(
    monkeypatch,
):
    presenter = make_failure_presenter()

    sync_repository = (
        FakeSyncRunRepository()
    )

    alert_service = FakeAlertService(
        fail_alert=True,
    )

    result = (
        failure_handler
        .handle_synchronization_failure(
            error=RuntimeError("boom"),
            sync_run_id=48,
            sync_run_repository=(
                sync_repository
            ),
            alert_service=alert_service,
            presenter=presenter,
        )
    )

    assert (
        result.sync_run_marked_failed
        is True
    )

    assert result.failure_alert is None

    assert len(sync_repository.calls) == 1


def test_both_secondary_failures_are_isolated(
    monkeypatch,
):
    presenter = make_failure_presenter()

    result = (
        failure_handler
        .handle_synchronization_failure(
            error=RuntimeError("original"),
            sync_run_id=49,
            sync_run_repository=(
                FakeSyncRunRepository(
                    fail_mark_failed=True,
                )
            ),
            alert_service=(
                FakeAlertService(
                    fail_alert=True,
                )
            ),
            presenter=presenter,
        )
    )

    assert (
        result.sync_run_marked_failed
        is False
    )

    assert result.failure_alert is None

    assert (
        result.error_message
        == "RuntimeError: original"
    )

    assert presenter.calls[0][
        "error_message"
    ] == "RuntimeError: original"


def test_failure_before_audit_id_skips_secondary_database_work(
    monkeypatch,
):
    presenter = make_failure_presenter()

    sync_repository = (
        FakeSyncRunRepository()
    )

    alert_service = FakeAlertService()

    result = (
        failure_handler
        .handle_synchronization_failure(
            error=RuntimeError(
                "start_run failed"
            ),
            sync_run_id=None,
            sync_run_repository=(
                sync_repository
            ),
            alert_service=alert_service,
            presenter=presenter,
        )
    )

    assert sync_repository.calls == []
    assert alert_service.calls == []

    assert (
        result.sync_run_marked_failed
        is False
    )

    assert result.failure_alert is None

    assert presenter.calls[0][
        "sync_run_id"
    ] is None


def test_failure_handler_preserves_original_exception_object(
    monkeypatch,
):
    """
    The helper observes the original exception but never raises a
    replacement exception of its own when secondary work succeeds.
    """

    presenter = make_failure_presenter()

    original = KeyError(
        "original failure"
    )

    result = (
        failure_handler
        .handle_synchronization_failure(
            error=original,
            sync_run_id=50,
            sync_run_repository=(
                FakeSyncRunRepository()
            ),
            alert_service=(
                FakeAlertService()
            ),
            presenter=presenter,
        )
    )

    assert result.error_type == "KeyError"

    assert (
        "original failure"
        in result.error_message
    )
