from __future__ import annotations

import argparse
import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from scripts.preflight import run_preflight
except ModuleNotFoundError:
    # Support direct execution:
    # python scripts/release_candidate_audit.py
    from preflight import run_preflight


REQUIRED_V1_FILES = (
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
)

README_REQUIREMENTS = (
    (
        "setup_or_installation",
        ("installation", "setup"),
        "Document how to install/setup the project.",
    ),
    (
        "configuration",
        ("configuration", ".env"),
        "Document environment/configuration setup.",
    ),
    (
        "testing",
        ("testing", "pytest"),
        "Document how to run the automated tests.",
    ),
    (
        "security",
        ("security", "secret"),
        "Document secret-handling/security expectations.",
    ),
    (
        "architecture",
        ("architecture",),
        "Document the current application architecture.",
    ),
    (
        "ci",
        (
            "continuous integration",
            "github actions",
            "ci",
        ),
        "Document the CI workflow.",
    ),
)

REQUIRED_CI_TOKENS = (
    "actions/checkout@",
    "actions/setup-python@",
    "python scripts/preflight.py --ci",
    "python -m compileall",
    "python -m pytest -q",
)

SENSITIVE_TRACKED_SUFFIXES = (
    ".db",
    ".db-shm",
    ".db-wal",
)

SENSITIVE_TRACKED_EXACT = (
    ".env",
)

SENSITIVE_TRACKED_PREFIXES = (
    "logs/",
    ".venv/",
)


@dataclass(frozen=True)
class AuditFinding:
    """
    One release-candidate audit finding.
    """

    category: str
    severity: str
    passed: bool
    message: str


@dataclass(frozen=True)
class ReleaseAuditResult:
    """
    Complete V1 release-candidate audit result.
    """

    findings: tuple[AuditFinding, ...]

    @property
    def blockers(self) -> tuple[AuditFinding, ...]:
        return tuple(
            finding
            for finding in self.findings
            if (
                not finding.passed
                and finding.severity
                == "BLOCKER"
            )
        )

    @property
    def warnings(self) -> tuple[AuditFinding, ...]:
        return tuple(
            finding
            for finding in self.findings
            if (
                not finding.passed
                and finding.severity
                == "WARNING"
            )
        )

    @property
    def status(self) -> str:
        if self.blockers:
            return "NOT READY"

        if self.warnings:
            return "READY WITH WARNINGS"

        return "READY"


def _read_text(
    path: Path,
) -> str:
    if not path.is_file():
        return ""

    return path.read_text(
        encoding="utf-8",
    )


def _git_lines(
    project_root: Path,
    *args: str,
) -> tuple[str, ...] | None:
    """
    Run one read-only Git command.

    None means Git was unavailable or the directory was not a repository.
    """

    completed = subprocess.run(
        (
            "git",
            *args,
        ),
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        return None

    return tuple(
        line
        for line in completed.stdout.splitlines()
        if line.strip()
    )


def _count_static_tests(
    tests_path: Path,
) -> tuple[int, int, int]:
    """
    Count test modules, test functions/methods, and parse errors.

    This is a static footprint check, not the runtime pytest result.
    Parametrization may make the pytest count larger than this count.
    """

    modules = 0
    test_functions = 0
    parse_errors = 0

    if not tests_path.is_dir():
        return (
            modules,
            test_functions,
            parse_errors,
        )

    for path in sorted(
        tests_path.glob("test_*.py")
    ):
        modules += 1

        try:
            tree = ast.parse(
                path.read_text(
                    encoding="utf-8",
                ),
                filename=str(path),
            )

        except SyntaxError:
            parse_errors += 1
            continue

        for node in ast.walk(tree):
            if (
                isinstance(
                    node,
                    (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                    ),
                )
                and node.name.startswith(
                    "test_"
                )
            ):
                test_functions += 1

    return (
        modules,
        test_functions,
        parse_errors,
    )


def _normalize_git_path(
    raw_name: str,
) -> str:
    """
    Normalize Git paths without stripping meaningful leading dots.

    Example:
        './.env' -> '.env'
        r'logs\\app.log' -> 'logs/app.log'
    """

    name = raw_name.replace(
        "\\",
        "/",
    )

    while name.startswith(
        "./"
    ):
        name = name[2:]

    return name


def _find_sensitive_tracked_files(
    tracked_files: Iterable[str],
) -> tuple[str, ...]:
    sensitive = []

    for raw_name in tracked_files:
        name = _normalize_git_path(
            raw_name
        )

        lowered = name.lower()

        if lowered in SENSITIVE_TRACKED_EXACT:
            sensitive.append(name)
            continue

        if any(
            lowered.startswith(prefix)
            for prefix
            in SENSITIVE_TRACKED_PREFIXES
        ):
            sensitive.append(name)
            continue

        if any(
            lowered.endswith(suffix)
            for suffix
            in SENSITIVE_TRACKED_SUFFIXES
        ):
            sensitive.append(name)

    return tuple(
        sorted(
            set(sensitive)
        )
    )


def _check_readme(
    readme_text: str,
) -> tuple[
    tuple[str, str],
    ...,
]:
    """
    Return missing README requirement names and guidance.
    """

    lowered = readme_text.lower()
    missing = []

    for (
        name,
        alternatives,
        guidance,
    ) in README_REQUIREMENTS:
        if not any(
            token in lowered
            for token in alternatives
        ):
            missing.append(
                (
                    name,
                    guidance,
                )
            )

    return tuple(missing)


def run_release_audit(
    *,
    project_root: Path,
    process_environment: dict[str, str] | None = None,
    git_status_lines: tuple[str, ...] | None = None,
    tracked_files: tuple[str, ...] | None = None,
    python_version: tuple[int, int, int] | None = None,
) -> ReleaseAuditResult:
    """
    Run a read-only V1 release-candidate audit.

    No Shopify requests, database mutations, Git writes, commits,
    pushes, or tags are performed.
    """

    project_root = (
        project_root.resolve()
    )

    findings: list[AuditFinding] = []

    preflight = run_preflight(
        project_root=project_root,
        process_environment=(
            process_environment
        ),
        python_version=python_version,
    )

    findings.append(
        AuditFinding(
            category="preflight",
            severity="BLOCKER",
            passed=preflight.passed,
            message=(
                "V1 preflight passes."
                if preflight.passed
                else (
                    "V1 preflight has "
                    f"{len(preflight.failures)} "
                    "failed check(s)."
                )
            ),
        )
    )

    missing_v1_files = tuple(
        path
        for path in REQUIRED_V1_FILES
        if not (
            project_root / path
        ).is_file()
    )

    findings.append(
        AuditFinding(
            category="v1_feature_footprint",
            severity="BLOCKER",
            passed=not missing_v1_files,
            message=(
                "Core V1 application modules are present."
                if not missing_v1_files
                else (
                    "Missing V1 modules: "
                    + ", ".join(
                        missing_v1_files
                    )
                )
            ),
        )
    )

    ci_path = (
        project_root
        / ".github"
        / "workflows"
        / "ci.yml"
    )

    ci_text = _read_text(
        ci_path
    ).lower()

    missing_ci_tokens = tuple(
        token
        for token in REQUIRED_CI_TOKENS
        if token.lower()
        not in ci_text
    )

    findings.append(
        AuditFinding(
            category="ci_definition",
            severity="BLOCKER",
            passed=(
                ci_path.is_file()
                and not missing_ci_tokens
            ),
            message=(
                "CI workflow contains preflight, compilation, and pytest gates."
                if (
                    ci_path.is_file()
                    and not missing_ci_tokens
                )
                else (
                    "CI workflow is missing required release gates: "
                    + ", ".join(
                        missing_ci_tokens
                    )
                )
            ),
        )
    )

    ci_runs_live_app = (
        "python main.py"
        in ci_text
    )

    findings.append(
        AuditFinding(
            category="ci_secret_safety",
            severity="BLOCKER",
            passed=not ci_runs_live_app,
            message=(
                "CI does not run the live Shopify entrypoint."
                if not ci_runs_live_app
                else (
                    "CI runs python main.py; remove live Shopify "
                    "execution from the test workflow."
                )
            ),
        )
    )

    (
        test_modules,
        static_test_functions,
        test_parse_errors,
    ) = _count_static_tests(
        project_root / "tests"
    )

    test_footprint_ok = (
        test_modules >= 20
        and static_test_functions >= 50
        and test_parse_errors == 0
    )

    findings.append(
        AuditFinding(
            category="test_footprint",
            severity="BLOCKER",
            passed=test_footprint_ok,
            message=(
                "Static test footprint: "
                f"{test_modules} modules, "
                f"{static_test_functions} test functions, "
                f"{test_parse_errors} parse errors."
            ),
        )
    )

    if git_status_lines is None:
        git_status_lines = _git_lines(
            project_root,
            "status",
            "--porcelain",
        )

    git_clean = (
        git_status_lines is not None
        and len(
            git_status_lines
        )
        == 0
    )

    findings.append(
        AuditFinding(
            category="git_cleanliness",
            severity="BLOCKER",
            passed=git_clean,
            message=(
                "Git working tree is clean."
                if git_clean
                else (
                    "Git working tree is not clean."
                    if git_status_lines
                    is not None
                    else (
                        "Git repository status could not be read."
                    )
                )
            ),
        )
    )

    if tracked_files is None:
        tracked_files = _git_lines(
            project_root,
            "ls-files",
        )

    sensitive_files = (
        _find_sensitive_tracked_files(
            tracked_files or ()
        )
        if tracked_files
        is not None
        else ()
    )

    sensitive_tracking_ok = (
        tracked_files is not None
        and not sensitive_files
    )

    findings.append(
        AuditFinding(
            category="tracked_secret_hygiene",
            severity="BLOCKER",
            passed=sensitive_tracking_ok,
            message=(
                "No .env, SQLite database, logs, or virtualenv files are tracked."
                if sensitive_tracking_ok
                else (
                    "Sensitive/local files tracked by Git: "
                    + (
                        ", ".join(
                            sensitive_files
                        )
                        if sensitive_files
                        else "Git tracked-file list unavailable."
                    )
                )
            ),
        )
    )

    env_example = _read_text(
        project_root
        / ".env.example"
    )

    required_example_keys = (
        "SHOPIFY_STORE_DOMAIN",
        "SHOPIFY_CLIENT_ID",
        "SHOPIFY_CLIENT_SECRET",
        "SHOPIFY_API_VERSION",
        "LOW_INVENTORY_THRESHOLD",
    )

    missing_example_keys = tuple(
        key
        for key
        in required_example_keys
        if key
        not in env_example
    )

    findings.append(
        AuditFinding(
            category="env_template",
            severity="BLOCKER",
            passed=not missing_example_keys,
            message=(
                ".env.example documents required configuration keys."
                if not missing_example_keys
                else (
                    ".env.example is missing: "
                    + ", ".join(
                        missing_example_keys
                    )
                )
            ),
        )
    )

    readme_text = _read_text(
        project_root / "README.md"
    )

    missing_readme = _check_readme(
        readme_text
    )

    documentation_blockers = {
        "setup_or_installation",
        "configuration",
        "testing",
        "security",
    }

    missing_blocking_docs = tuple(
        item
        for item in missing_readme
        if item[0]
        in documentation_blockers
    )

    missing_warning_docs = tuple(
        item
        for item in missing_readme
        if item[0]
        not in documentation_blockers
    )

    findings.append(
        AuditFinding(
            category="readme_operability",
            severity="BLOCKER",
            passed=not missing_blocking_docs,
            message=(
                "README contains setup, configuration, testing, and security guidance."
                if not missing_blocking_docs
                else (
                    "README release documentation gaps: "
                    + "; ".join(
                        guidance
                        for _, guidance
                        in missing_blocking_docs
                    )
                )
            ),
        )
    )

    findings.append(
        AuditFinding(
            category="readme_architecture_ci",
            severity="WARNING",
            passed=not missing_warning_docs,
            message=(
                "README documents architecture and CI."
                if not missing_warning_docs
                else (
                    "README improvement opportunities: "
                    + "; ".join(
                        guidance
                        for _, guidance
                        in missing_warning_docs
                    )
                )
            ),
        )
    )

    license_present = any(
        (
            project_root / name
        ).is_file()
        for name in (
            "LICENSE",
            "LICENSE.md",
            "LICENSE.txt",
        )
    )

    findings.append(
        AuditFinding(
            category="license",
            severity="WARNING",
            passed=license_present,
            message=(
                "Repository includes a license file."
                if license_present
                else (
                    "No license file found. Add one before "
                    "public distribution if appropriate."
                )
            ),
        )
    )

    return ReleaseAuditResult(
        findings=tuple(findings)
    )


def print_result(
    result: ReleaseAuditResult,
) -> None:
    print(
        "SHOPIFY AUTOMATION LAB — V1 RELEASE CANDIDATE AUDIT"
    )
    print("=" * 68)

    for finding in result.findings:
        marker = (
            "PASS"
            if finding.passed
            else finding.severity
        )

        print(
            f"[{marker}] "
            f"{finding.category}: "
            f"{finding.message}"
        )

    print("=" * 68)
    print(
        "RELEASE CANDIDATE STATUS:",
        result.status,
    )
    print(
        "Blockers:",
        len(
            result.blockers
        ),
    )
    print(
        "Warnings:",
        len(
            result.warnings
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the read-only Shopify Automation Lab "
            "V1 release-candidate audit."
        )
    )

    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
    )

    return parser


def main() -> int:
    args = (
        build_parser()
        .parse_args()
    )

    project_root = (
        args.project_root.resolve()
        if args.project_root
        is not None
        else (
            Path(__file__)
            .resolve()
            .parent
            .parent
        )
    )

    result = run_release_audit(
        project_root=project_root
    )

    print_result(
        result
    )

    return (
        0
        if result.status
        != "NOT READY"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
