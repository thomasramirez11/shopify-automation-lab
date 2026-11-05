from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path


SECTION_PATTERN = re.compile(
    r"^\s*#\s*(?P<title>.+?)\s*$"
)


IGNORED_COMMENT_TITLES = {
    "",
    "--------------------------------------------------",
}


CATEGORY_RULES = (
    (
        "bootstrap",
        (
            "failure-safe",
            "create application services",
            "create repositories",
            "create alert and financial processing services",
            "dependency",
            "dependencies",
        ),
    ),
    (
        "shopify_connection",
        (
            "shopify client",
            "authenticate",
            "authentication",
        ),
    ),
    (
        "product_flow",
        (
            "product",
            "products",
            "low-inventory",
            "low inventory",
        ),
    ),
    (
        "order_flow",
        (
            "order",
            "orders",
            "new-order",
            "new order",
        ),
    ),
    (
        "financial_flow",
        (
            "financial",
            "profit",
            "cost",
            "snapshot",
        ),
    ),
    (
        "reporting",
        (
            "daily report",
            "report",
            "store health",
        ),
    ),
    (
        "verification",
        (
            "verify",
            "verification",
            "read product data back",
            "read order data back",
            "database state",
        ),
    ),
    (
        "sync_audit",
        (
            "synchronization audit",
            "mark synchronization successful",
            "recent synchronization",
            "sync run",
        ),
    ),
    (
        "failure_handling",
        (
            "failure",
            "failed",
            "exception",
            "error",
        ),
    ),
)


@dataclass(frozen=True)
class Section:
    """
    One comment-delimited responsibility inside main.py.
    """

    title: str
    start_line: int
    end_line: int
    category: str


@dataclass(frozen=True)
class MainMetrics:
    """
    Static metrics describing the current main.py.
    """

    total_lines: int
    main_start_line: int | None
    main_end_line: int | None
    main_body_lines: int
    print_calls: int
    logger_calls: int
    try_blocks: int
    except_handlers: int
    constructor_calls: tuple[str, ...]
    environment_reads: tuple[str, ...]


@dataclass(frozen=True)
class ResponsibilityMap:
    """
    Complete static map of the project entrypoint.
    """

    sections: tuple[Section, ...]
    metrics: MainMetrics
    parse_error: str | None


def normalize_section_title(
    raw_title: str,
) -> str:
    """
    Remove optional numbering such as '10B.' or '23.'.
    """

    title = raw_title.strip()

    title = re.sub(
        r"^\d+[A-Za-z]?\.\s*",
        "",
        title,
    )

    return title.strip()


def categorize_section(
    title: str,
) -> str:
    """
    Map one section title to a broad orchestration responsibility.

    This is intentionally heuristic. It is used to organize the
    refactor discussion, not to change application behavior.
    """

    normalized = title.lower()

    for category, keywords in CATEGORY_RULES:
        if any(
            keyword in normalized
            for keyword in keywords
        ):
            return category

    return "other"


def extract_sections(
    source: str,
) -> list[Section]:
    """
    Extract meaningful comment headings and their line ranges.
    """

    lines = source.splitlines()

    headings: list[
        tuple[int, str]
    ] = []

    for line_number, line in enumerate(
        lines,
        start=1,
    ):
        match = SECTION_PATTERN.match(
            line
        )

        if match is None:
            continue

        raw_title = (
            match.group("title")
            .strip()
        )

        if raw_title in IGNORED_COMMENT_TITLES:
            continue

        # Ignore normal prose comments. Responsibility headings in
        # this project are either numbered or short title-like lines.
        is_numbered = bool(
            re.match(
                r"^\d+[A-Za-z]?\.\s+",
                raw_title,
            )
        )

        title = normalize_section_title(
            raw_title
        )

        title_like = (
            len(title) <= 70
            and not title.endswith(".")
        )

        if not (
            is_numbered
            or title_like
        ):
            continue

        headings.append(
            (
                line_number,
                title,
            )
        )

    sections = []

    for index, (
        start_line,
        title,
    ) in enumerate(headings):
        if index + 1 < len(headings):
            end_line = (
                headings[index + 1][0]
                - 1
            )
        else:
            end_line = len(lines)

        sections.append(
            Section(
                title=title,
                start_line=start_line,
                end_line=end_line,
                category=categorize_section(
                    title
                ),
            )
        )

    return sections


def _call_name(
    node: ast.Call,
) -> str | None:
    """
    Return a readable name for one function/class call.
    """

    function = node.func

    if isinstance(
        function,
        ast.Name,
    ):
        return function.id

    if isinstance(
        function,
        ast.Attribute,
    ):
        parts = [
            function.attr
        ]

        value = function.value

        while isinstance(
            value,
            ast.Attribute,
        ):
            parts.append(
                value.attr
            )
            value = value.value

        if isinstance(
            value,
            ast.Name,
        ):
            parts.append(
                value.id
            )

        return ".".join(
            reversed(parts)
        )

    return None


def _is_constructor_name(
    name: str,
) -> bool:
    """
    Heuristic for project class construction calls.
    """

    final_name = name.split(".")[-1]

    return (
        final_name
        and final_name[0].isupper()
    )


def collect_metrics(
    source: str,
) -> MainMetrics:
    """
    Collect static metrics from main.py without importing it.
    """

    lines = source.splitlines()

    tree = ast.parse(
        source
    )

    main_function = None

    for node in tree.body:
        if (
            isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name == "main"
        ):
            main_function = node
            break

    print_calls = 0
    logger_calls = 0
    try_blocks = 0
    except_handlers = 0
    constructor_calls: set[str] = set()
    environment_reads: set[str] = set()

    nodes = (
        ast.walk(main_function)
        if main_function is not None
        else ast.walk(tree)
    )

    for node in nodes:
        if isinstance(
            node,
            ast.Try,
        ):
            try_blocks += 1
            except_handlers += len(
                node.handlers
            )

        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        name = _call_name(
            node
        )

        if name == "print":
            print_calls += 1

        if (
            name is not None
            and name.startswith(
                "logger."
            )
        ):
            logger_calls += 1

        if (
            name is not None
            and _is_constructor_name(
                name
            )
        ):
            constructor_calls.add(
                name
            )

        if name in {
            "os.getenv",
            "os.environ.get",
        }:
            if (
                node.args
                and isinstance(
                    node.args[0],
                    ast.Constant,
                )
                and isinstance(
                    node.args[0].value,
                    str,
                )
            ):
                environment_reads.add(
                    node.args[0].value
                )

    if main_function is None:
        main_start_line = None
        main_end_line = None
        main_body_lines = 0

    else:
        main_start_line = (
            main_function.lineno
        )

        main_end_line = getattr(
            main_function,
            "end_lineno",
            main_function.lineno,
        )

        main_body_lines = (
            main_end_line
            - main_start_line
            + 1
        )

    return MainMetrics(
        total_lines=len(lines),
        main_start_line=main_start_line,
        main_end_line=main_end_line,
        main_body_lines=main_body_lines,
        print_calls=print_calls,
        logger_calls=logger_calls,
        try_blocks=try_blocks,
        except_handlers=except_handlers,
        constructor_calls=tuple(
            sorted(
                constructor_calls
            )
        ),
        environment_reads=tuple(
            sorted(
                environment_reads
            )
        ),
    )


def build_responsibility_map(
    main_path: Path,
) -> ResponsibilityMap:
    """
    Build a read-only responsibility map for main.py.
    """

    source = main_path.read_text(
        encoding="utf-8",
    )

    sections = tuple(
        extract_sections(
            source
        )
    )

    try:
        metrics = collect_metrics(
            source
        )

    except SyntaxError as exc:
        return ResponsibilityMap(
            sections=sections,
            metrics=MainMetrics(
                total_lines=len(
                    source.splitlines()
                ),
                main_start_line=None,
                main_end_line=None,
                main_body_lines=0,
                print_calls=0,
                logger_calls=0,
                try_blocks=0,
                except_handlers=0,
                constructor_calls=(),
                environment_reads=(),
            ),
            parse_error=(
                f"line {exc.lineno or '?'}: "
                f"{exc.msg}"
            ),
        )

    return ResponsibilityMap(
        sections=sections,
        metrics=metrics,
        parse_error=None,
    )


def group_sections(
    sections: tuple[Section, ...],
) -> dict[str, list[Section]]:
    """
    Group sections by responsibility category.
    """

    grouped: dict[
        str,
        list[Section],
    ] = {}

    for section in sections:
        grouped.setdefault(
            section.category,
            [],
        ).append(section)

    return grouped


def print_responsibility_map(
    result: ResponsibilityMap,
    main_path: Path,
) -> None:
    """
    Print a human-readable refactor map.
    """

    print(
        "SHOPIFY AUTOMATION LAB — "
        "MAIN.PY RESPONSIBILITY MAP"
    )

    print("=" * 64)

    print(
        "File:",
        main_path.resolve(),
    )

    print(
        "Total lines:",
        result.metrics.total_lines,
    )

    if result.parse_error is not None:
        print(
            "Parse error:",
            result.parse_error,
        )

        return

    print(
        "main() lines:",
        (
            f"{result.metrics.main_start_line}"
            "-"
            f"{result.metrics.main_end_line}"
        ),
    )

    print(
        "main() size:",
        result.metrics.main_body_lines,
        "lines",
    )

    print(
        "print() calls:",
        result.metrics.print_calls,
    )

    print(
        "logger calls:",
        result.metrics.logger_calls,
    )

    print(
        "try blocks:",
        result.metrics.try_blocks,
    )

    print(
        "except handlers:",
        result.metrics.except_handlers,
    )

    print(
        "dependency constructors:",
        len(
            result.metrics.constructor_calls
        ),
    )

    print(
        "environment reads:",
        len(
            result.metrics.environment_reads
        ),
    )

    print()
    print("CONSTRUCTED DEPENDENCIES")
    print("-" * 64)

    if not result.metrics.constructor_calls:
        print(
            "None detected."
        )

    else:
        for name in (
            result.metrics
            .constructor_calls
        ):
            print(
                f"- {name}"
            )

    print()
    print("ENVIRONMENT READS")
    print("-" * 64)

    if not result.metrics.environment_reads:
        print(
            "None detected."
        )

    else:
        for name in (
            result.metrics
            .environment_reads
        ):
            print(
                f"- {name}"
            )

    print()
    print("RESPONSIBILITY GROUPS")
    print("-" * 64)

    grouped = group_sections(
        result.sections
    )

    preferred_order = (
        "bootstrap",
        "shopify_connection",
        "product_flow",
        "order_flow",
        "financial_flow",
        "reporting",
        "verification",
        "sync_audit",
        "failure_handling",
        "other",
    )

    for category in preferred_order:
        sections = grouped.get(
            category
        )

        if not sections:
            continue

        print()
        print(
            category.upper()
        )

        for section in sections:
            print(
                "  "
                f"L{section.start_line}-"
                f"L{section.end_line}"
                " | "
                f"{section.title}"
            )

    print()
    print("REFACTOR SIGNALS")
    print("-" * 64)

    signals = []

    if (
        result.metrics
        .main_body_lines
        > 500
    ):
        signals.append(
            "main() is larger than 500 lines."
        )

    if (
        result.metrics
        .print_calls
        > 25
    ):
        signals.append(
            "Terminal presentation is a major responsibility."
        )

    if (
        len(
            result.metrics
            .constructor_calls
        )
        >= 6
    ):
        signals.append(
            "Dependency construction is a major responsibility."
        )

    if len(grouped) >= 5:
        signals.append(
            "main.py coordinates many business responsibilities."
        )

    if not signals:
        print(
            "No strong extraction signals detected."
        )

    else:
        for signal in signals:
            print(
                f"- {signal}"
            )

    print()
    print("RECOMMENDED EXTRACTION ORDER")
    print("-" * 64)

    print(
        "1. Dependency construction / application bootstrap"
    )
    print(
        "2. Terminal presentation helpers"
    )
    print(
        "3. Synchronization orchestration workflow"
    )
    print(
        "4. Failure-reporting orchestration"
    )
    print(
        "5. Reporting orchestration, if still embedded in main.py"
    )

    print()
    print(
        "This command is read-only. "
        "No project files or database rows were modified."
    )


def build_parser() -> argparse.ArgumentParser:
    """
    Build command-line arguments.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Map the responsibilities currently living "
            "inside Shopify Automation Lab main.py."
        )
    )

    parser.add_argument(
        "--main",
        type=Path,
        default=None,
        help=(
            "Path to main.py. Defaults to the project-root "
            "main.py next to scripts/."
        ),
    )

    return parser


def main() -> None:
    """
    CLI entrypoint.
    """

    parser = build_parser()
    args = parser.parse_args()

    if args.main is None:
        main_path = (
            Path(__file__)
            .resolve()
            .parent
            .parent
            / "main.py"
        )
    else:
        main_path = (
            args.main
            .resolve()
        )

    if not main_path.is_file():
        parser.error(
            f"main.py not found: {main_path}"
        )

    result = build_responsibility_map(
        main_path
    )

    print_responsibility_map(
        result,
        main_path,
    )


if __name__ == "__main__":
    main()
