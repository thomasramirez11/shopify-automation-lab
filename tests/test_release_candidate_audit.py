from pathlib import Path

from scripts.release_candidate_audit import (
    _find_sensitive_tracked_files,
    _count_static_tests,
    run_release_audit,
)


VALID_ENV = {
    "SHOPIFY_STORE_DOMAIN":
        "example.myshopify.com",
    "SHOPIFY_CLIENT_ID":
        "test-client",
    "SHOPIFY_CLIENT_SECRET":
        "test-secret",
    "SHOPIFY_API_VERSION":
        "2026-07",
    "LOW_INVENTORY_THRESHOLD":
        "5",
}


def build_project(
    tmp_path: Path,
    *,
    complete_readme: bool = True,
) -> Path:
    for directory in (
        "application",
        "config",
        "database",
        "presentation",
        "repositories",
        "services",
        "shopify",
        "scripts",
        "tests",
        ".github/workflows",
    ):
        (
            tmp_path / directory
        ).mkdir(
            parents=True,
            exist_ok=True,
        )

    for path in (
        "application/sync_workflow.py",
        "application/product_sync_workflow.py",
        "application/inventory_alert_workflow.py",
        "application/order_sync_workflow.py",
        "application/financial_workflow.py",
        "application/sync_completion_workflow.py",
        "application/reporting_workflow.py",
        "application/failure_handler.py",
        "application/presentation_ports.py",
        "database/integrity.py",
        "main.py",
    ):
        (
            tmp_path / path
        ).write_text(
            "pass\n",
            encoding="utf-8",
        )

    (
        tmp_path / ".env.example"
    ).write_text(
        (
            "SHOPIFY_STORE_DOMAIN=\n"
            "SHOPIFY_CLIENT_ID=\n"
            "SHOPIFY_CLIENT_SECRET=\n"
            "SHOPIFY_API_VERSION=2026-07\n"
            "LOW_INVENTORY_THRESHOLD=5\n"
        ),
        encoding="utf-8",
    )

    (
        tmp_path / ".env"
    ).write_text(
        (
            "SHOPIFY_STORE_DOMAIN=example.myshopify.com\n"
            "SHOPIFY_CLIENT_ID=test-client\n"
            "SHOPIFY_CLIENT_SECRET=test-secret\n"
            "SHOPIFY_API_VERSION=2026-07\n"
            "LOW_INVENTORY_THRESHOLD=5\n"
        ),
        encoding="utf-8",
    )

    (
        tmp_path / ".gitignore"
    ).write_text(
        (
            ".env\n"
            ".venv/\n"
            "__pycache__/\n"
            "*.pyc\n"
            "*.db\n"
            "logs/\n"
        ),
        encoding="utf-8",
    )

    (
        tmp_path / "requirements.txt"
    ).write_text(
        (
            "python-dotenv==1.2.3\n"
            "requests==2.34.2\n"
            "tzdata==2026.5\n"
        ),
        encoding="utf-8",
    )

    (
        tmp_path
        / "requirements-dev.txt"
    ).write_text(
        "pytest==9.1.1\n",
        encoding="utf-8",
    )

    (
        tmp_path
        / ".github"
        / "workflows"
        / "ci.yml"
    ).write_text(
        (
            "uses: actions/checkout@v4\n"
            "uses: actions/setup-python@v5\n"
            "run: python scripts/preflight.py --ci\n"
            "run: python -m compileall application tests\n"
            "run: python -m pytest -q\n"
        ),
        encoding="utf-8",
    )

    if complete_readme:
        readme = """
# Project
## Installation
Setup instructions.
## Configuration
Use .env and never commit a secret.
## Testing
Run pytest.
## Security
Keep secrets private.
## Architecture
Application architecture.
## Continuous Integration
GitHub Actions runs CI.
"""
    else:
        readme = """
# Project
## Architecture
Architecture notes only.
"""

    (
        tmp_path / "README.md"
    ).write_text(
        readme,
        encoding="utf-8",
    )

    (
        tmp_path / "LICENSE"
    ).write_text(
        "Example license\n",
        encoding="utf-8",
    )

    for module_index in range(20):
        lines = []

        for test_index in range(3):
            lines.append(
                (
                    "def test_"
                    f"{module_index}_"
                    f"{test_index}():\n"
                    "    assert True\n"
                )
            )

        (
            tmp_path
            / "tests"
            / f"test_module_{module_index}.py"
        ).write_text(
            "\n".join(lines),
            encoding="utf-8",
        )

    return tmp_path


def test_clean_release_candidate_can_be_ready(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    result = run_release_audit(
        project_root=root,
        process_environment=VALID_ENV,
        git_status_lines=(),
        tracked_files=(
            "main.py",
            "README.md",
        ),
        python_version=(3, 13, 14),
    )

    assert result.status == "READY"
    assert result.blockers == ()


def test_dirty_git_tree_is_blocker(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    result = run_release_audit(
        project_root=root,
        process_environment=VALID_ENV,
        git_status_lines=(
            "?? stray.txt",
        ),
        tracked_files=("main.py",),
        python_version=(3, 13, 14),
    )

    assert result.status == "NOT READY"

    assert any(
        finding.category
        == "git_cleanliness"
        for finding in result.blockers
    )


def test_tracked_env_file_is_blocker(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    result = run_release_audit(
        project_root=root,
        process_environment=VALID_ENV,
        git_status_lines=(),
        tracked_files=(
            ".env",
            "main.py",
        ),
        python_version=(3, 13, 14),
    )

    assert result.status == "NOT READY"


def test_tracked_database_is_blocker(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    result = run_release_audit(
        project_root=root,
        process_environment=VALID_ENV,
        git_status_lines=(),
        tracked_files=(
            "data/shopify.db",
            "main.py",
        ),
        python_version=(3, 13, 14),
    )

    assert result.status == "NOT READY"


def test_sensitive_file_detection_normalizes_windows_paths():
    result = (
        _find_sensitive_tracked_files(
            (
                r"logs\app.log",
                r"data\shopify.db",
                ".env",
            )
        )
    )

    assert ".env" in result
    assert "data/shopify.db" in result
    assert "logs/app.log" in result


def test_incomplete_readme_blocks_release_operability(
    tmp_path,
):
    root = build_project(
        tmp_path,
        complete_readme=False,
    )

    result = run_release_audit(
        project_root=root,
        process_environment=VALID_ENV,
        git_status_lines=(),
        tracked_files=("main.py",),
        python_version=(3, 13, 14),
    )

    assert result.status == "NOT READY"

    assert any(
        finding.category
        == "readme_operability"
        for finding in result.blockers
    )


def test_missing_license_is_warning_not_blocker(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    (
        root / "LICENSE"
    ).unlink()

    result = run_release_audit(
        project_root=root,
        process_environment=VALID_ENV,
        git_status_lines=(),
        tracked_files=("main.py",),
        python_version=(3, 13, 14),
    )

    assert (
        result.status
        == "READY WITH WARNINGS"
    )


def test_ci_running_live_main_is_blocker(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    ci_path = (
        root
        / ".github"
        / "workflows"
        / "ci.yml"
    )

    ci_path.write_text(
        ci_path.read_text(
            encoding="utf-8"
        )
        + "run: python main.py\n",
        encoding="utf-8",
    )

    result = run_release_audit(
        project_root=root,
        process_environment=VALID_ENV,
        git_status_lines=(),
        tracked_files=("main.py",),
        python_version=(3, 13, 14),
    )

    assert result.status == "NOT READY"

    assert any(
        finding.category
        == "ci_secret_safety"
        for finding in result.blockers
    )


def test_missing_ci_gate_is_blocker(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    (
        root
        / ".github"
        / "workflows"
        / "ci.yml"
    ).write_text(
        "uses: actions/checkout@v4\n",
        encoding="utf-8",
    )

    result = run_release_audit(
        project_root=root,
        process_environment=VALID_ENV,
        git_status_lines=(),
        tracked_files=("main.py",),
        python_version=(3, 13, 14),
    )

    assert result.status == "NOT READY"


def test_missing_core_v1_module_is_blocker(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    (
        root
        / "application"
        / "financial_workflow.py"
    ).unlink()

    result = run_release_audit(
        project_root=root,
        process_environment=VALID_ENV,
        git_status_lines=(),
        tracked_files=("main.py",),
        python_version=(3, 13, 14),
    )

    assert result.status == "NOT READY"


def test_missing_env_example_key_is_blocker(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    (
        root / ".env.example"
    ).write_text(
        (
            "SHOPIFY_STORE_DOMAIN=\n"
            "SHOPIFY_CLIENT_ID=\n"
            "SHOPIFY_CLIENT_SECRET=\n"
            "SHOPIFY_API_VERSION=2026-07\n"
        ),
        encoding="utf-8",
    )

    result = run_release_audit(
        project_root=root,
        process_environment=VALID_ENV,
        git_status_lines=(),
        tracked_files=("main.py",),
        python_version=(3, 13, 14),
    )

    assert result.status == "NOT READY"


def test_test_footprint_requires_many_modules_and_tests(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    for path in (
        root / "tests"
    ).glob("test_*.py"):
        path.unlink()

    (
        root
        / "tests"
        / "test_small.py"
    ).write_text(
        (
            "def test_one():\n"
            "    assert True\n"
        ),
        encoding="utf-8",
    )

    result = run_release_audit(
        project_root=root,
        process_environment=VALID_ENV,
        git_status_lines=(),
        tracked_files=("main.py",),
        python_version=(3, 13, 14),
    )

    assert result.status == "NOT READY"


def test_static_test_counter_reports_parse_errors(
    tmp_path,
):
    tests = (
        tmp_path / "tests"
    )
    tests.mkdir()

    (
        tests / "test_good.py"
    ).write_text(
        (
            "def test_one():\n"
            "    assert True\n"
        ),
        encoding="utf-8",
    )

    (
        tests / "test_bad.py"
    ).write_text(
        "def broken(:\n",
        encoding="utf-8",
    )

    modules, functions, errors = (
        _count_static_tests(
            tests
        )
    )

    assert modules == 2
    assert functions == 1
    assert errors == 1
