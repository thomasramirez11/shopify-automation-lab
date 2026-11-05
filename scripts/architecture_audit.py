from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path


EXCLUDED_DIRECTORIES = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "data",
    "logs",
    "venv",
}


LAYER_RULES = {
    "config": {
        "database",
        "main",
        "repositories",
        "services",
        "shopify",
    },
    "database": {
        "main",
        "repositories",
        "services",
        "shopify",
    },
    "shopify": {
        "database",
        "main",
        "repositories",
        "services",
    },
    "repositories": {
        "main",
        "services",
        "shopify",
    },
    "services": {
        "main",
    },
}


@dataclass(frozen=True)
class ModuleInfo:
    """
    Static information collected from one Python module.
    """

    module_name: str
    path: Path
    line_count: int
    imports: tuple[str, ...]


@dataclass(frozen=True)
class ArchitectureViolation:
    """
    One suspicious dependency between architectural layers.
    """

    source_module: str
    target_module: str
    source_layer: str
    target_layer: str


@dataclass(frozen=True)
class AuditResult:
    """
    Complete read-only architecture audit result.
    """

    modules: tuple[ModuleInfo, ...]
    local_import_edges: tuple[tuple[str, str], ...]
    violations: tuple[ArchitectureViolation, ...]
    cycles: tuple[tuple[str, ...], ...]
    parse_errors: tuple[str, ...]


def should_ignore_path(
    path: Path,
    project_root: Path,
) -> bool:
    """
    Return True when a path belongs to a generated/local directory
    that should not be included in the architecture audit.
    """

    try:
        relative = path.relative_to(project_root)
    except ValueError:
        return True

    return any(
        part in EXCLUDED_DIRECTORIES
        for part in relative.parts
    )


def discover_python_files(
    project_root: Path,
) -> list[Path]:
    """
    Return project Python files in deterministic path order.
    """

    files = []

    for path in project_root.rglob("*.py"):
        if should_ignore_path(
            path,
            project_root,
        ):
            continue

        files.append(path)

    return sorted(files)


def module_name_from_path(
    path: Path,
    project_root: Path,
) -> str:
    """
    Convert a project-relative Python path into an import-like name.

    Examples:
        main.py -> main
        services/profit_service.py -> services.profit_service
        services/__init__.py -> services
    """

    relative = path.relative_to(
        project_root
    )

    without_suffix = relative.with_suffix("")

    parts = list(
        without_suffix.parts
    )

    if parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def collect_imports(
    source: str,
) -> tuple[str, ...]:
    """
    Parse one Python source string and return imported module names.

    Relative imports are represented by their explicit module name when
    one exists. The audit intentionally stays static and never imports
    project code, so it cannot trigger application side effects.
    """

    tree = ast.parse(source)

    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(
                    alias.name
                )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            if node.module:
                imports.add(
                    node.module
                )

    return tuple(
        sorted(imports)
    )


def top_level_name(
    module_name: str,
) -> str:
    """
    Return the first component of a dotted module name.
    """

    return module_name.split(
        ".",
        maxsplit=1,
    )[0]


def source_layer_for_module(
    module_name: str,
) -> str:
    """
    Map one module to the architectural layer used by the audit.
    """

    if module_name == "main":
        return "main"

    return top_level_name(
        module_name
    )


def build_local_module_names(
    modules: list[ModuleInfo],
) -> set[str]:
    """
    Return exact local module names known to the project.
    """

    return {
        module.module_name
        for module in modules
        if module.module_name
    }


def resolve_local_target(
    imported_name: str,
    local_module_names: set[str],
) -> str | None:
    """
    Resolve an imported module name to a local project module.

    An exact module is preferred. If code imports a package or nested
    member that is not itself represented by a file, the longest known
    local module prefix is returned.
    """

    if imported_name in local_module_names:
        return imported_name

    parts = imported_name.split(".")

    for index in range(
        len(parts) - 1,
        0,
        -1,
    ):
        candidate = ".".join(
            parts[:index]
        )

        if candidate in local_module_names:
            return candidate

    return None


def find_architecture_violations(
    local_import_edges: list[tuple[str, str]],
) -> list[ArchitectureViolation]:
    """
    Return suspicious reverse/cross-layer dependencies.

    These rules are intentionally conservative. They flag architecture
    smells for review; they do not modify code or claim every warning
    is automatically a bug.
    """

    violations = []

    for source, target in local_import_edges:
        source_layer = (
            source_layer_for_module(
                source
            )
        )

        target_layer = (
            source_layer_for_module(
                target
            )
        )

        forbidden_targets = (
            LAYER_RULES.get(
                source_layer,
                set(),
            )
        )

        if target_layer not in forbidden_targets:
            continue

        violations.append(
            ArchitectureViolation(
                source_module=source,
                target_module=target,
                source_layer=source_layer,
                target_layer=target_layer,
            )
        )

    return sorted(
        violations,
        key=lambda item: (
            item.source_module,
            item.target_module,
        ),
    )


def find_cycles(
    local_import_edges: list[tuple[str, str]],
) -> list[tuple[str, ...]]:
    """
    Find simple module dependency cycles.

    Results are normalized so the same cycle is not reported multiple
    times merely because traversal began from a different module.
    """

    graph: dict[str, set[str]] = {}

    for source, target in local_import_edges:
        graph.setdefault(
            source,
            set(),
        ).add(target)

        graph.setdefault(
            target,
            set(),
        )

    cycles: set[tuple[str, ...]] = set()

    def canonicalize_cycle(
        cycle: list[str],
    ) -> tuple[str, ...]:
        body = cycle[:-1]

        rotations = [
            tuple(
                body[index:]
                + body[:index]
            )
            for index in range(
                len(body)
            )
        ]

        canonical = min(rotations)

        return canonical + (
            canonical[0],
        )

    def visit(
        node: str,
        path: list[str],
        path_set: set[str],
    ) -> None:
        for neighbor in sorted(
            graph.get(
                node,
                set(),
            )
        ):
            if neighbor in path_set:
                start_index = path.index(
                    neighbor
                )

                cycle = (
                    path[start_index:]
                    + [neighbor]
                )

                cycles.add(
                    canonicalize_cycle(
                        cycle
                    )
                )

                continue

            visit(
                neighbor,
                path + [neighbor],
                path_set | {neighbor},
            )

    for node in sorted(graph):
        visit(
            node,
            [node],
            {node},
        )

    return sorted(cycles)


def audit_project(
    project_root: Path,
) -> AuditResult:
    """
    Run a read-only architecture audit of one Python project.
    """

    project_root = (
        project_root
        .resolve()
    )

    modules = []
    parse_errors = []

    for path in discover_python_files(
        project_root
    ):
        module_name = (
            module_name_from_path(
                path,
                project_root,
            )
        )

        source = path.read_text(
            encoding="utf-8",
        )

        line_count = len(
            source.splitlines()
        )

        try:
            imports = collect_imports(
                source
            )

        except SyntaxError as exc:
            imports = ()

            parse_errors.append(
                (
                    f"{path.relative_to(project_root)}:"
                    f"{exc.lineno or '?'} "
                    f"{exc.msg}"
                )
            )

        modules.append(
            ModuleInfo(
                module_name=module_name,
                path=path,
                line_count=line_count,
                imports=imports,
            )
        )

    local_module_names = (
        build_local_module_names(
            modules
        )
    )

    edges: set[tuple[str, str]] = set()

    for module in modules:
        for imported_name in module.imports:
            target = resolve_local_target(
                imported_name,
                local_module_names,
            )

            if target is None:
                continue

            if target == module.module_name:
                continue

            edges.add(
                (
                    module.module_name,
                    target,
                )
            )

    edge_list = sorted(edges)

    return AuditResult(
        modules=tuple(modules),
        local_import_edges=tuple(edge_list),
        violations=tuple(
            find_architecture_violations(
                edge_list
            )
        ),
        cycles=tuple(
            find_cycles(
                edge_list
            )
        ),
        parse_errors=tuple(
            sorted(parse_errors)
        ),
    )


def print_audit_report(
    result: AuditResult,
    project_root: Path,
    *,
    large_file_threshold: int = 500,
    top_files: int = 10,
) -> None:
    """
    Print a compact architecture report for human review.
    """

    print(
        "SHOPIFY AUTOMATION LAB — "
        "ARCHITECTURE AUDIT"
    )

    print("=" * 58)
    print(
        "Project root:",
        project_root.resolve(),
    )
    print(
        "Python files:",
        len(result.modules),
    )
    print(
        "Local import edges:",
        len(
            result.local_import_edges
        ),
    )
    print(
        "Architecture warnings:",
        len(result.violations),
    )
    print(
        "Dependency cycles:",
        len(result.cycles),
    )
    print(
        "Parse errors:",
        len(result.parse_errors),
    )

    print()
    print("LARGEST PYTHON FILES")
    print("-" * 58)

    largest = sorted(
        result.modules,
        key=lambda item: (
            -item.line_count,
            item.module_name,
        ),
    )[:top_files]

    for module in largest:
        relative = module.path.relative_to(
            project_root.resolve()
        )

        marker = (
            "  <-- REVIEW"
            if module.line_count
            >= large_file_threshold
            else ""
        )

        print(
            f"{module.line_count:5d} lines | "
            f"{relative}"
            f"{marker}"
        )

    print()
    print("ARCHITECTURE WARNINGS")
    print("-" * 58)

    if not result.violations:
        print(
            "No suspicious cross-layer imports detected."
        )

    else:
        for violation in result.violations:
            print(
                f"{violation.source_module}"
                " -> "
                f"{violation.target_module}"
                "  "
                f"[{violation.source_layer}"
                " -> "
                f"{violation.target_layer}]"
            )

    print()
    print("DEPENDENCY CYCLES")
    print("-" * 58)

    if not result.cycles:
        print(
            "No local import cycles detected."
        )

    else:
        for cycle in result.cycles:
            print(
                " -> ".join(cycle)
            )

    print()
    print("PARSE ERRORS")
    print("-" * 58)

    if not result.parse_errors:
        print(
            "No Python parse errors detected."
        )

    else:
        for parse_error in result.parse_errors:
            print(parse_error)

    print()
    print("=" * 58)

    if (
        not result.violations
        and not result.cycles
        and not result.parse_errors
    ):
        print(
            "Architecture audit status: CLEAN"
        )

    else:
        print(
            "Architecture audit status: REVIEW NEEDED"
        )

    print(
        "Note: architecture warnings are review signals, "
        "not automatic defects."
    )


def build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line parser.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Run a read-only static architecture audit "
            "of the Shopify Automation Lab project."
        )
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "Project root. Defaults to the parent "
            "directory of scripts/."
        ),
    )

    parser.add_argument(
        "--large-file-threshold",
        type=int,
        default=500,
        help=(
            "Line count used to mark large modules "
            "for review."
        ),
    )

    parser.add_argument(
        "--top-files",
        type=int,
        default=10,
        help=(
            "Number of largest Python files to display."
        ),
    )

    return parser


def main() -> None:
    """
    CLI entrypoint.
    """

    parser = build_parser()
    args = parser.parse_args()

    if args.root is None:
        project_root = (
            Path(__file__)
            .resolve()
            .parent
            .parent
        )
    else:
        project_root = (
            args.root
            .resolve()
        )

    if (
        args.large_file_threshold
        < 1
    ):
        parser.error(
            "--large-file-threshold "
            "must be at least 1"
        )

    if args.top_files < 1:
        parser.error(
            "--top-files must be at least 1"
        )

    result = audit_project(
        project_root
    )

    print_audit_report(
        result,
        project_root,
        large_file_threshold=(
            args.large_file_threshold
        ),
        top_files=args.top_files,
    )


if __name__ == "__main__":
    main()
