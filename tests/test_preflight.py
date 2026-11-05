from pathlib import Path

from scripts.preflight import (
    run_preflight,
)


VALID_ENV = {
    "SHOPIFY_STORE_DOMAIN":
        "example.myshopify.com",
    "SHOPIFY_CLIENT_ID":
        "test-client-id",
    "SHOPIFY_CLIENT_SECRET":
        "test-client-secret",
    "SHOPIFY_API_VERSION":
        "2026-07",
    "LOW_INVENTORY_THRESHOLD":
        "5",
}


def build_project(
    tmp_path: Path,
) -> Path:
    for directory in (
        "application",
        "config",
        "database",
        "presentation",
        "repositories",
        "services",
        "shopify",
        "tests",
    ):
        (
            tmp_path / directory
        ).mkdir()

    (
        tmp_path / "main.py"
    ).write_text(
        "def main():\n    pass\n",
        encoding="utf-8",
    )

    (
        tmp_path
        / "requirements.txt"
    ).write_text(
        "\n".join(
            (
                "python-dotenv==1.2.3",
                "requests==2.34.2",
                "tzdata==2026.5",
            )
        )
        + "\n",
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
        tmp_path / ".gitignore"
    ).write_text(
        "\n".join(
            (
                ".env",
                ".venv/",
                "__pycache__/",
                "*.pyc",
                "*.db",
                "logs/",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    (
        tmp_path / ".env"
    ).write_text(
        (
            "SHOPIFY_STORE_DOMAIN=local.myshopify.com\n"
            "SHOPIFY_CLIENT_ID=local-id\n"
            "SHOPIFY_CLIENT_SECRET=local-secret\n"
            "SHOPIFY_API_VERSION=2026-07\n"
            "LOW_INVENTORY_THRESHOLD=5\n"
        ),
        encoding="utf-8",
    )

    return tmp_path


def checks_by_name(
    result,
):
    return {
        check.name: check
        for check in result.checks
    }


def test_happy_path_local_preflight_passes(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    result = run_preflight(
        project_root=root,
        process_environment={},
        python_version=(3, 13, 14),
    )

    assert result.passed is True


def test_ci_mode_does_not_require_local_env_file(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    (
        root / ".env"
    ).unlink()

    result = run_preflight(
        project_root=root,
        process_environment=VALID_ENV,
        ci_mode=True,
        python_version=(3, 13, 0),
    )

    assert result.passed is True


def test_missing_required_environment_is_reported(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    (
        root / ".env"
    ).unlink()

    environment = dict(
        VALID_ENV
    )

    environment.pop(
        "SHOPIFY_CLIENT_SECRET"
    )

    result = run_preflight(
        project_root=root,
        process_environment=environment,
        ci_mode=True,
        python_version=(3, 13, 0),
    )

    check = checks_by_name(
        result
    )["required_environment"]

    assert check.passed is False

    assert (
        "SHOPIFY_CLIENT_SECRET"
        in check.message
    )

    assert (
        "test-client"
        not in check.message
    )


def test_python_below_minimum_fails(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    result = run_preflight(
        project_root=root,
        process_environment=VALID_ENV,
        ci_mode=True,
        python_version=(3, 12, 9),
    )

    assert (
        checks_by_name(result)[
            "python_version"
        ].passed
        is False
    )


def test_invalid_api_version_fails(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    environment = dict(
        VALID_ENV
    )

    environment[
        "SHOPIFY_API_VERSION"
    ] = "bad-version"

    result = run_preflight(
        project_root=root,
        process_environment=environment,
        ci_mode=True,
        python_version=(3, 13, 0),
    )

    assert (
        checks_by_name(result)[
            "api_version_format"
        ].passed
        is False
    )


def test_negative_inventory_threshold_fails(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    environment = dict(
        VALID_ENV
    )

    environment[
        "LOW_INVENTORY_THRESHOLD"
    ] = "-1"

    result = run_preflight(
        project_root=root,
        process_environment=environment,
        ci_mode=True,
        python_version=(3, 13, 0),
    )

    assert (
        checks_by_name(result)[
            "inventory_threshold"
        ].passed
        is False
    )


def test_non_integer_inventory_threshold_fails(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    environment = dict(
        VALID_ENV
    )

    environment[
        "LOW_INVENTORY_THRESHOLD"
    ] = "hello"

    result = run_preflight(
        project_root=root,
        process_environment=environment,
        ci_mode=True,
        python_version=(3, 13, 0),
    )

    assert (
        checks_by_name(result)[
            "inventory_threshold"
        ].passed
        is False
    )


def test_missing_runtime_dependency_fails(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    (
        root
        / "requirements.txt"
    ).write_text(
        (
            "python-dotenv==1.2.3\n"
            "requests==2.34.2\n"
        ),
        encoding="utf-8",
    )

    result = run_preflight(
        project_root=root,
        process_environment=VALID_ENV,
        ci_mode=True,
        python_version=(3, 13, 0),
    )

    check = checks_by_name(
        result
    )["runtime_requirements"]

    assert check.passed is False
    assert "tzdata" in check.message


def test_missing_pytest_dependency_fails(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    (
        root
        / "requirements-dev.txt"
    ).write_text(
        "# empty\n",
        encoding="utf-8",
    )

    result = run_preflight(
        project_root=root,
        process_environment=VALID_ENV,
        ci_mode=True,
        python_version=(3, 13, 0),
    )

    assert (
        checks_by_name(result)[
            "development_requirements"
        ].passed
        is False
    )


def test_missing_gitignore_secret_rule_fails(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    (
        root / ".gitignore"
    ).write_text(
        (
            ".venv/\n"
            "__pycache__/\n"
            "*.pyc\n"
            "*.db\n"
            "logs/\n"
        ),
        encoding="utf-8",
    )

    result = run_preflight(
        project_root=root,
        process_environment=VALID_ENV,
        ci_mode=True,
        python_version=(3, 13, 0),
    )

    check = checks_by_name(
        result
    )["gitignore_security"]

    assert check.passed is False
    assert ".env" in check.message


def test_missing_project_directory_fails(
    tmp_path,
):
    root = build_project(
        tmp_path
    )

    (
        root / "application"
    ).rmdir()

    result = run_preflight(
        project_root=root,
        process_environment=VALID_ENV,
        ci_mode=True,
        python_version=(3, 13, 0),
    )

    check = checks_by_name(
        result
    )["project_directories"]

    assert check.passed is False

    assert (
        "application"
        in check.message
    )
