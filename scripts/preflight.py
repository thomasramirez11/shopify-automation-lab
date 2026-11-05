from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


MINIMUM_PYTHON = (3, 13)

REQUIRED_DIRECTORIES = (
    "application",
    "config",
    "database",
    "presentation",
    "repositories",
    "services",
    "shopify",
    "tests",
)

REQUIRED_FILES = (
    "main.py",
    "requirements.txt",
    "requirements-dev.txt",
    ".env.example",
    ".gitignore",
)

REQUIRED_ENVIRONMENT_VARIABLES = (
    "SHOPIFY_STORE_DOMAIN",
    "SHOPIFY_CLIENT_ID",
    "SHOPIFY_CLIENT_SECRET",
    "SHOPIFY_API_VERSION",
)

RUNTIME_REQUIREMENTS = (
    "python-dotenv",
    "requests",
    "tzdata",
)

DEVELOPMENT_REQUIREMENTS = (
    "pytest",
)

REQUIRED_GITIGNORE_PATTERNS = (
    ".env",
    ".venv/",
    "__pycache__/",
    "*.pyc",
    "*.db",
    "logs/",
)

API_VERSION_PATTERN = re.compile(
    r"^\d{4}-(0[1-9]|1[0-2])$"
)


@dataclass(frozen=True)
class CheckResult:
    """
    One release-readiness preflight check.
    """

    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class PreflightResult:
    """
    Complete preflight outcome.
    """

    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(
            check.passed
            for check in self.checks
        )

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(
            check
            for check in self.checks
            if not check.passed
        )


def _normalized_requirement_lines(
    path: Path,
) -> tuple[str, ...]:
    """
    Return active requirement lines in lowercase.

    This deliberately avoids importing/installing packages while
    checking the dependency manifests.
    """

    if not path.is_file():
        return ()

    lines = []

    for raw_line in path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()

        if (
            not line
            or line.startswith("#")
        ):
            continue

        lines.append(
            line.lower()
        )

    return tuple(lines)


def _requirement_is_present(
    requirement_lines: tuple[str, ...],
    package_name: str,
) -> bool:
    """
    Match a package name at the beginning of a requirement line.
    """

    normalized_name = (
        package_name.lower()
    )

    return any(
        line == normalized_name
        or line.startswith(
            (
                normalized_name + "==",
                normalized_name + ">=",
                normalized_name + "<=",
                normalized_name + "~=",
                normalized_name + ">",
                normalized_name + "<",
                normalized_name + "[",
            )
        )
        for line in requirement_lines
    )


def _load_effective_environment(
    *,
    project_root: Path,
    process_environment: Mapping[str, str],
    ci_mode: bool,
) -> dict[str, str]:
    """
    Build the configuration view used by preflight.

    In local mode, values from .env are read without printing them.
    Real process environment variables take precedence.

    CI mode deliberately does not read .env.
    """

    effective: dict[str, str] = {}

    if not ci_mode:
        env_path = (
            project_root / ".env"
        )

        if env_path.is_file():
            file_values = dotenv_values(
                env_path
            )

            for key, value in (
                file_values.items()
            ):
                if (
                    key
                    and value is not None
                ):
                    effective[key] = value

    for key, value in (
        process_environment.items()
    ):
        effective[key] = value

    return effective


def run_preflight(
    *,
    project_root: Path,
    process_environment: Mapping[str, str] | None = None,
    ci_mode: bool = False,
    python_version: tuple[int, int, int] | None = None,
) -> PreflightResult:
    """
    Run V1 release-readiness checks without contacting Shopify.

    No credential values are included in result messages.
    """

    project_root = (
        project_root.resolve()
    )

    environment = (
        process_environment
        if process_environment is not None
        else os.environ
    )

    version = (
        python_version
        if python_version is not None
        else (
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )
    )

    checks: list[CheckResult] = []

    python_ok = (
        version[:2]
        >= MINIMUM_PYTHON
    )

    checks.append(
        CheckResult(
            name="python_version",
            passed=python_ok,
            message=(
                f"Python {version[0]}.{version[1]}.{version[2]} "
                f"(minimum {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]})."
            ),
        )
    )

    missing_directories = [
        name
        for name in REQUIRED_DIRECTORIES
        if not (
            project_root / name
        ).is_dir()
    ]

    checks.append(
        CheckResult(
            name="project_directories",
            passed=not missing_directories,
            message=(
                "Required project directories are present."
                if not missing_directories
                else (
                    "Missing directories: "
                    + ", ".join(
                        missing_directories
                    )
                )
            ),
        )
    )

    missing_files = [
        name
        for name in REQUIRED_FILES
        if not (
            project_root / name
        ).is_file()
    ]

    checks.append(
        CheckResult(
            name="project_files",
            passed=not missing_files,
            message=(
                "Required project files are present."
                if not missing_files
                else (
                    "Missing files: "
                    + ", ".join(
                        missing_files
                    )
                )
            ),
        )
    )

    env_file_exists = (
        project_root / ".env"
    ).is_file()

    checks.append(
        CheckResult(
            name="local_env_file",
            passed=(
                True
                if ci_mode
                else env_file_exists
            ),
            message=(
                "CI mode: local .env is intentionally not required."
                if ci_mode
                else (
                    "Local .env file is present."
                    if env_file_exists
                    else (
                        "Local .env is missing. "
                        "Create it from .env.example."
                    )
                )
            ),
        )
    )

    effective_environment = (
        _load_effective_environment(
            project_root=project_root,
            process_environment=environment,
            ci_mode=ci_mode,
        )
    )

    missing_environment = [
        name
        for name in REQUIRED_ENVIRONMENT_VARIABLES
        if not str(
            effective_environment.get(
                name,
                "",
            )
        ).strip()
    ]

    checks.append(
        CheckResult(
            name="required_environment",
            passed=not missing_environment,
            message=(
                "Required Shopify configuration is present."
                if not missing_environment
                else (
                    "Missing configuration keys: "
                    + ", ".join(
                        missing_environment
                    )
                )
            ),
        )
    )

    api_version = str(
        effective_environment.get(
            "SHOPIFY_API_VERSION",
            "",
        )
    ).strip()

    api_version_ok = bool(
        API_VERSION_PATTERN.fullmatch(
            api_version
        )
    )

    checks.append(
        CheckResult(
            name="api_version_format",
            passed=api_version_ok,
            message=(
                "SHOPIFY_API_VERSION uses YYYY-MM format."
                if api_version_ok
                else (
                    "SHOPIFY_API_VERSION must use "
                    "YYYY-MM format."
                )
            ),
        )
    )

    threshold_raw = str(
        effective_environment.get(
            "LOW_INVENTORY_THRESHOLD",
            "5",
        )
    ).strip()

    try:
        threshold = int(
            threshold_raw
        )

        threshold_ok = (
            threshold >= 0
        )

    except ValueError:
        threshold_ok = False

    checks.append(
        CheckResult(
            name="inventory_threshold",
            passed=threshold_ok,
            message=(
                "LOW_INVENTORY_THRESHOLD is a non-negative integer."
                if threshold_ok
                else (
                    "LOW_INVENTORY_THRESHOLD must be "
                    "a non-negative integer."
                )
            ),
        )
    )

    runtime_lines = (
        _normalized_requirement_lines(
            project_root
            / "requirements.txt"
        )
    )

    missing_runtime = [
        package
        for package in RUNTIME_REQUIREMENTS
        if not _requirement_is_present(
            runtime_lines,
            package,
        )
    ]

    checks.append(
        CheckResult(
            name="runtime_requirements",
            passed=not missing_runtime,
            message=(
                "Runtime dependency manifest contains required packages."
                if not missing_runtime
                else (
                    "requirements.txt is missing: "
                    + ", ".join(
                        missing_runtime
                    )
                )
            ),
        )
    )

    dev_lines = (
        _normalized_requirement_lines(
            project_root
            / "requirements-dev.txt"
        )
    )

    missing_dev = [
        package
        for package in DEVELOPMENT_REQUIREMENTS
        if not _requirement_is_present(
            dev_lines,
            package,
        )
    ]

    checks.append(
        CheckResult(
            name="development_requirements",
            passed=not missing_dev,
            message=(
                "Development dependency manifest contains pytest."
                if not missing_dev
                else (
                    "requirements-dev.txt is missing: "
                    + ", ".join(
                        missing_dev
                    )
                )
            ),
        )
    )

    gitignore_path = (
        project_root / ".gitignore"
    )

    gitignore_text = (
        gitignore_path.read_text(
            encoding="utf-8"
        )
        if gitignore_path.is_file()
        else ""
    )

    gitignore_lines = {
        line.strip()
        for line in (
            gitignore_text.splitlines()
        )
        if (
            line.strip()
            and not line.strip().startswith(
                "#"
            )
        )
    }

    missing_ignore_patterns = [
        pattern
        for pattern
        in REQUIRED_GITIGNORE_PATTERNS
        if pattern not in gitignore_lines
    ]

    checks.append(
        CheckResult(
            name="gitignore_security",
            passed=not missing_ignore_patterns,
            message=(
                "Sensitive/local artifact ignore rules are present."
                if not missing_ignore_patterns
                else (
                    ".gitignore is missing patterns: "
                    + ", ".join(
                        missing_ignore_patterns
                    )
                )
            ),
        )
    )

    return PreflightResult(
        checks=tuple(checks)
    )


def print_result(
    result: PreflightResult,
) -> None:
    """
    Print a credential-safe preflight summary.
    """

    print(
        "SHOPIFY AUTOMATION LAB — V1 PREFLIGHT"
    )
    print("=" * 52)

    for check in result.checks:
        marker = (
            "PASS"
            if check.passed
            else "FAIL"
        )

        print(
            f"[{marker}] "
            f"{check.name}: "
            f"{check.message}"
        )

    print("=" * 52)

    if result.passed:
        print(
            "PREFLIGHT STATUS: READY"
        )

    else:
        print(
            "PREFLIGHT STATUS: NOT READY"
        )

        print(
            f"Failed checks: "
            f"{len(result.failures)}"
        )


def build_parser() -> argparse.ArgumentParser:
    """
    Build CLI arguments.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Run credential-safe V1 release-readiness "
            "checks without contacting Shopify."
        )
    )

    parser.add_argument(
        "--ci",
        action="store_true",
        help=(
            "CI mode: do not require or load a local .env file."
        ),
    )

    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help=(
            "Project root override. Defaults to the "
            "parent directory of scripts/."
        ),
    )

    return parser


def main() -> int:
    """
    CLI entrypoint.
    """

    parser = build_parser()
    args = parser.parse_args()

    project_root = (
        args.project_root.resolve()
        if args.project_root is not None
        else (
            Path(__file__)
            .resolve()
            .parent
            .parent
        )
    )

    result = run_preflight(
        project_root=project_root,
        ci_mode=args.ci,
    )

    print_result(
        result
    )

    return (
        0
        if result.passed
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
