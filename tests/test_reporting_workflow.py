import application.reporting_workflow as reporting_workflow


class FakeDailyReportService:
    def __init__(
        self,
        *,
        result=None,
        error=None,
    ):
        self.result = result
        self.error = error
        self.calls = 0

    def generate_and_save_report(self):
        self.calls += 1

        if self.error is not None:
            raise self.error

        return self.result


class BuilderRecorder:
    def __init__(
        self,
        service,
    ):
        self.service = service
        self.calls = []

    def __call__(
        self,
        **kwargs,
    ):
        self.calls.append(kwargs)
        return self.service


def success_result():
    return {
        "report_id": 9,
        "formatted_report": "REPORT",
        "report": {
            "health": {
                "status": "healthy",
            }
        },
    }


class RecordingReportingPresenter:
    def __init__(
        self,
        *,
        fail_success=False,
        fail_failure=False,
    ):
        self.success_calls = []
        self.failure_calls = []
        self.fail_success = fail_success
        self.fail_failure = fail_failure

    def show_daily_report_success(
        self,
        result,
    ):
        if self.fail_success:
            raise RuntimeError(
                "success presenter failed"
            )

        self.success_calls.append(result)

    def show_daily_report_failure(self):
        if self.fail_failure:
            raise RuntimeError(
                "presenter failed"
            )

        self.failure_calls.append(True)


def repositories():
    return {
        "product_repository": object(),
        "order_repository": object(),
        "alert_repository": object(),
        "sync_run_repository": object(),
        "profit_snapshot_repository": (
            object()
        ),
    }


def test_success_returns_structured_result(
    monkeypatch,
):
    presenter = RecordingReportingPresenter()

    service = FakeDailyReportService(
        result=success_result(),
    )

    builder = BuilderRecorder(
        service
    )

    result = (
        reporting_workflow
        .run_reporting_workflow(
            sync_run_id=63,
            daily_report_service_builder=(
                builder
            ),
            presenter=presenter,
            **repositories(),
        )
    )

    assert result.success is True
    assert result.report_id == 9
    assert result.health_status == "healthy"
    assert result.error_type is None
    assert result.error_message is None

    assert service.calls == 1
    assert len(presenter.success_calls) == 1
    assert presenter.failure_calls == []


def test_builder_receives_existing_repositories(
    monkeypatch,
):
    presenter = RecordingReportingPresenter()

    repos = repositories()

    builder = BuilderRecorder(
        FakeDailyReportService(
            result=success_result(),
        )
    )

    reporting_workflow.run_reporting_workflow(
        sync_run_id=63,
        daily_report_service_builder=(
            builder
        ),
        presenter=presenter,
        **repos,
    )

    assert builder.calls == [
        repos
    ]


def test_report_generation_failure_is_isolated(
    monkeypatch,
):
    presenter = RecordingReportingPresenter()

    service = FakeDailyReportService(
        error=RuntimeError(
            "report generation failed"
        )
    )

    result = (
        reporting_workflow
        .run_reporting_workflow(
            sync_run_id=63,
            daily_report_service_builder=(
                BuilderRecorder(
                    service
                )
            ),
            presenter=presenter,
            **repositories(),
        )
    )

    assert result.success is False
    assert result.report_id is None
    assert result.health_status is None
    assert result.error_type == "RuntimeError"
    assert (
        result.error_message
        == (
            "RuntimeError: "
            "report generation failed"
        )
    )

    assert presenter.success_calls == []
    assert presenter.failure_calls == [True]


def test_builder_failure_is_isolated(
    monkeypatch,
):
    presenter = RecordingReportingPresenter()

    def failing_builder(
        **kwargs,
    ):
        raise ValueError(
            "builder failed"
        )

    result = (
        reporting_workflow
        .run_reporting_workflow(
            sync_run_id=64,
            daily_report_service_builder=(
                failing_builder
            ),
            presenter=presenter,
            **repositories(),
        )
    )

    assert result.success is False
    assert result.error_type == "ValueError"
    assert (
        "builder failed"
        in result.error_message
    )
    assert presenter.failure_calls == [True]


def test_failure_presenter_failure_is_also_isolated(
    monkeypatch,
):
    presenter = RecordingReportingPresenter(
        fail_failure=True,
    )

    result = (
        reporting_workflow
        .run_reporting_workflow(
            sync_run_id=65,
            daily_report_service_builder=(
                BuilderRecorder(
                    FakeDailyReportService(
                        error=RuntimeError(
                            "report failed"
                        )
                    )
                )
            ),
            presenter=presenter,
            **repositories(),
        )
    )

    assert result.success is False
    assert (
        result.error_message
        == "RuntimeError: report failed"
    )


def test_success_presenter_failure_is_treated_as_reporting_failure(
    monkeypatch,
):
    presenter = RecordingReportingPresenter(
        fail_success=True,
    )

    result = (
        reporting_workflow
        .run_reporting_workflow(
            sync_run_id=66,
            daily_report_service_builder=(
                BuilderRecorder(
                    FakeDailyReportService(
                        result=success_result(),
                    )
                )
            ),
            presenter=presenter,
            **repositories(),
        )
    )

    assert result.success is False
    assert result.report_id is None
    assert (
        result.error_type
        == "RuntimeError"
    )
    assert presenter.failure_calls == [True]
