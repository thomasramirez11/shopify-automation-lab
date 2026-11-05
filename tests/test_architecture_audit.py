from pathlib import Path

from scripts.architecture_audit import (
    ArchitectureViolation,
    audit_project,
    collect_imports,
    discover_python_files,
    find_architecture_violations,
    find_cycles,
    module_name_from_path,
    resolve_local_target,
    should_ignore_path,
    source_layer_for_module,
)


def write_file(
    root: Path,
    relative_path: str,
    contents: str,
) -> Path:
    path = root / relative_path

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        contents,
        encoding="utf-8",
    )

    return path


def test_ignore_generated_and_local_directories(
    tmp_path,
):
    ignored = (
        tmp_path
        / ".venv"
        / "module.py"
    )

    assert should_ignore_path(
        ignored,
        tmp_path,
    )


def test_discover_python_files_excludes_local_artifacts(
    tmp_path,
):
    write_file(
        tmp_path,
        "services/good.py",
        "VALUE = 1\n",
    )

    write_file(
        tmp_path,
        ".venv/bad.py",
        "VALUE = 2\n",
    )

    write_file(
        tmp_path,
        "logs/bad.py",
        "VALUE = 3\n",
    )

    files = discover_python_files(
        tmp_path
    )

    assert [
        path.relative_to(tmp_path)
        for path in files
    ] == [
        Path("services/good.py")
    ]


def test_module_name_for_regular_module(
    tmp_path,
):
    path = (
        tmp_path
        / "services"
        / "profit_service.py"
    )

    assert module_name_from_path(
        path,
        tmp_path,
    ) == "services.profit_service"


def test_module_name_for_package_init(
    tmp_path,
):
    path = (
        tmp_path
        / "services"
        / "__init__.py"
    )

    assert module_name_from_path(
        path,
        tmp_path,
    ) == "services"


def test_collect_imports_reads_import_and_from_import(
):
    imports = collect_imports(
        """
import logging
import repositories.order_repository
from services.profit_service import ProfitService
"""
    )

    assert imports == (
        "logging",
        "repositories.order_repository",
        "services.profit_service",
    )


def test_resolve_local_target_prefers_exact_module(
):
    local_modules = {
        "services",
        "services.profit_service",
    }

    assert resolve_local_target(
        "services.profit_service",
        local_modules,
    ) == "services.profit_service"


def test_resolve_local_target_uses_known_prefix(
):
    local_modules = {
        "services",
        "services.profit_service",
    }

    assert resolve_local_target(
        "services.profit_service.Helper",
        local_modules,
    ) == "services.profit_service"


def test_source_layer_for_main(
):
    assert source_layer_for_module(
        "main"
    ) == "main"


def test_repository_importing_service_is_flagged(
):
    violations = (
        find_architecture_violations(
            [
                (
                    "repositories.order_repository",
                    "services.order_service",
                )
            ]
        )
    )

    assert violations == [
        ArchitectureViolation(
            source_module=(
                "repositories.order_repository"
            ),
            target_module=(
                "services.order_service"
            ),
            source_layer="repositories",
            target_layer="services",
        )
    ]


def test_service_importing_repository_is_allowed(
):
    violations = (
        find_architecture_violations(
            [
                (
                    "services.order_service",
                    "repositories.order_repository",
                )
            ]
        )
    )

    assert violations == []


def test_database_importing_service_is_flagged(
):
    violations = (
        find_architecture_violations(
            [
                (
                    "database.connection",
                    "services.order_service",
                )
            ]
        )
    )

    assert len(violations) == 1


def test_find_cycles_detects_simple_cycle(
):
    cycles = find_cycles(
        [
            ("services.a", "repositories.b"),
            ("repositories.b", "services.a"),
        ]
    )

    assert cycles == [
        (
            "repositories.b",
            "services.a",
            "repositories.b",
        )
    ]


def test_find_cycles_returns_empty_for_acyclic_graph(
):
    cycles = find_cycles(
        [
            ("main", "services.a"),
            ("services.a", "repositories.b"),
            ("repositories.b", "database.connection"),
        ]
    )

    assert cycles == []


def test_audit_project_collects_modules_and_edges(
    tmp_path,
):
    write_file(
        tmp_path,
        "database/connection.py",
        "VALUE = 1\n",
    )

    write_file(
        tmp_path,
        "repositories/order_repository.py",
        (
            "from database.connection "
            "import VALUE\n"
        ),
    )

    write_file(
        tmp_path,
        "services/order_service.py",
        (
            "from repositories.order_repository "
            "import VALUE\n"
        ),
    )

    result = audit_project(
        tmp_path
    )

    module_names = {
        module.module_name
        for module in result.modules
    }

    assert module_names == {
        "database.connection",
        "repositories.order_repository",
        "services.order_service",
    }

    assert (
        "repositories.order_repository",
        "database.connection",
    ) in result.local_import_edges

    assert (
        "services.order_service",
        "repositories.order_repository",
    ) in result.local_import_edges


def test_audit_project_reports_syntax_errors_without_importing_code(
    tmp_path,
):
    write_file(
        tmp_path,
        "services/broken.py",
        "def broken(:\n",
    )

    result = audit_project(
        tmp_path
    )

    assert len(
        result.parse_errors
    ) == 1

    normalized_error = (
        result.parse_errors[0]
        .replace("\\", "/")
    )

    assert (
        "services/broken.py"
        in normalized_error
    )
