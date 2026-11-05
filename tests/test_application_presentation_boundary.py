import ast
from pathlib import Path

from application.presentation_ports import (
    FailurePresenter,
    ReportingPresenter,
    SyncWorkflowPresenter,
)
from presentation.terminal_workflow_presenter import (
    TerminalWorkflowPresenter,
)


APPLICATION_MODULES = (
    Path(
        "application/"
        "product_sync_workflow.py"
    ),
    Path(
        "application/"
        "financial_workflow.py"
    ),
    Path(
        "application/"
        "sync_completion_workflow.py"
    ),
    Path(
        "application/"
        "inventory_alert_workflow.py"
    ),
    Path(
        "application/"
        "order_sync_workflow.py"
    ),
    Path(
        "application/"
        "sync_workflow.py"
    ),
    Path(
        "application/"
        "failure_handler.py"
    ),
    Path(
        "application/"
        "reporting_workflow.py"
    ),
)


def imported_roots(path):
    tree = ast.parse(
        path.read_text(
            encoding="utf-8",
        )
    )

    roots = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(
                    alias.name.split(".")[0]
                )

        elif (
            isinstance(
                node,
                ast.ImportFrom,
            )
            and node.module
        ):
            roots.add(
                node.module.split(".")[0]
            )

    return roots


def test_application_workflows_do_not_import_presentation_layer():
    for path in APPLICATION_MODULES:
        assert (
            "presentation"
            not in imported_roots(path)
        ), (
            f"{path} must depend on "
            "application presentation ports, "
            "not the CLI layer."
        )


def test_terminal_adapter_satisfies_sync_presenter_contract():
    presenter = (
        TerminalWorkflowPresenter()
    )

    assert isinstance(
        presenter,
        SyncWorkflowPresenter,
    )


def test_terminal_adapter_satisfies_failure_presenter_contract():
    presenter = (
        TerminalWorkflowPresenter()
    )

    assert isinstance(
        presenter,
        FailurePresenter,
    )


def test_terminal_adapter_satisfies_reporting_presenter_contract():
    presenter = (
        TerminalWorkflowPresenter()
    )

    assert isinstance(
        presenter,
        ReportingPresenter,
    )
