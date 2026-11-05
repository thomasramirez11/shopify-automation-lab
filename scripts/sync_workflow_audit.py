
from __future__ import annotations

import argparse
import ast
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

SECTION_PATTERN = re.compile(r"^\s*#\s*(?P<title>.+?)\s*$")

# Priority matters: specific meanings must beat broad words like "order".
CATEGORY_RULES = (
    ("verification", (
        "verify", "verification", "read product data back",
        "read order data back", "database state", "persistence test",
    )),
    ("inventory_alerts", (
        "inventory", "low-inventory", "low inventory",
    )),
    ("financial_processing", (
        "financial", "profit", "missing-cost", "missing cost",
        "snapshot", "cost", "finances",
    )),
    ("sync_audit", (
        "mark synchronization successful", "synchronization audit",
        "recent synchronization", "sync run",
    )),
    ("product_sync", ("product", "products")),
    ("order_sync", ("order", "orders", "new-order", "new order")),
)

KEY_RECEIVERS = {
    "product_service", "order_service", "product_repository",
    "order_repository", "profit_snapshot_repository",
    "financial_processing_service", "alert_repository",
    "alert_service", "sync_run_repository", "presenter",
}

@dataclass(frozen=True)
class WorkflowSection:
    title: str
    start_line: int
    end_line: int
    line_count: int
    category: str

@dataclass(frozen=True)
class ReceiverUsage:
    receiver: str
    call_count: int
    methods: tuple[str, ...]

@dataclass(frozen=True)
class WorkflowMetrics:
    total_file_lines: int
    function_start_line: int | None
    function_end_line: int | None
    function_lines: int
    parameter_count: int
    local_assignment_count: int
    if_count: int
    for_count: int
    try_count: int
    raise_count: int
    return_count: int

@dataclass(frozen=True)
class WorkflowAuditResult:
    metrics: WorkflowMetrics
    sections: tuple[WorkflowSection, ...]
    receiver_usage: tuple[ReceiverUsage, ...]
    category_line_counts: tuple[tuple[str, int], ...]
    result_fields: tuple[str, ...]
    parse_error: str | None

def normalize_section_title(raw_title: str) -> str:
    return re.sub(r"^\d+[A-Za-z]?\.\s*", "", raw_title.strip()).strip()

def categorize_section(title: str) -> str:
    normalized = title.lower()
    for category, keywords in CATEGORY_RULES:
        if any(keyword in normalized for keyword in keywords):
            return category
    return "other"

def extract_sections(source: str) -> list[WorkflowSection]:
    lines = source.splitlines()
    headings: list[tuple[int, str]] = []

    for line_number, line in enumerate(lines, start=1):
        match = SECTION_PATTERN.match(line)
        if match is None:
            continue

        raw = match.group("title").strip()
        if not raw or set(raw) <= {"-"}:
            continue

        is_numbered = bool(re.match(r"^\d+[A-Za-z]?\.\s+", raw))
        title = normalize_section_title(raw)
        title_like = len(title) <= 80 and not title.endswith(".")

        if is_numbered or title_like:
            headings.append((line_number, title))

    sections: list[WorkflowSection] = []
    for index, (start_line, title) in enumerate(headings):
        end_line = headings[index + 1][0] - 1 if index + 1 < len(headings) else len(lines)
        sections.append(
            WorkflowSection(
                title=title,
                start_line=start_line,
                end_line=end_line,
                line_count=end_line - start_line + 1,
                category=categorize_section(title),
            )
        )
    return sections

def find_workflow_function(tree: ast.Module) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run_synchronization_workflow":
            return node
    return None

def collect_receiver_usage(function: ast.FunctionDef) -> tuple[ReceiverUsage, ...]:
    methods: dict[str, list[str]] = {name: [] for name in KEY_RECEIVERS}
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name):
            continue
        receiver = node.func.value.id
        if receiver in methods:
            methods[receiver].append(node.func.attr)

    return tuple(
        ReceiverUsage(
            receiver=name,
            call_count=len(values),
            methods=tuple(sorted(set(values))),
        )
        for name, values in sorted(methods.items())
        if values
    )

def collect_result_fields(tree: ast.Module) -> tuple[str, ...]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SyncWorkflowResult":
            return tuple(
                child.target.id
                for child in node.body
                if isinstance(child, ast.AnnAssign)
                and isinstance(child.target, ast.Name)
            )
    return ()

def build_metrics(source: str, function: ast.FunctionDef | None) -> WorkflowMetrics:
    total = len(source.splitlines())
    if function is None:
        return WorkflowMetrics(total, None, None, 0, 0, 0, 0, 0, 0, 0, 0)

    end = getattr(function, "end_lineno", function.lineno)
    return WorkflowMetrics(
        total_file_lines=total,
        function_start_line=function.lineno,
        function_end_line=end,
        function_lines=end - function.lineno + 1,
        parameter_count=len(function.args.args) + len(function.args.kwonlyargs),
        local_assignment_count=sum(
            isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
            for node in ast.walk(function)
        ),
        if_count=sum(isinstance(node, ast.If) for node in ast.walk(function)),
        for_count=sum(isinstance(node, (ast.For, ast.AsyncFor)) for node in ast.walk(function)),
        try_count=sum(isinstance(node, ast.Try) for node in ast.walk(function)),
        raise_count=sum(isinstance(node, ast.Raise) for node in ast.walk(function)),
        return_count=sum(isinstance(node, ast.Return) for node in ast.walk(function)),
    )

def summarize_category_lines(sections: list[WorkflowSection]) -> tuple[tuple[str, int], ...]:
    counts = Counter()
    for section in sections:
        counts[section.category] += section.line_count
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

def audit_sync_workflow(workflow_path: Path) -> WorkflowAuditResult:
    source = workflow_path.read_text(encoding="utf-8")
    sections = extract_sections(source)

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return WorkflowAuditResult(
            metrics=build_metrics(source, None),
            sections=tuple(sections),
            receiver_usage=(),
            category_line_counts=summarize_category_lines(sections),
            result_fields=(),
            parse_error=f"line {exc.lineno or '?'}: {exc.msg}",
        )

    function = find_workflow_function(tree)
    return WorkflowAuditResult(
        metrics=build_metrics(source, function),
        sections=tuple(sections),
        receiver_usage=collect_receiver_usage(function) if function else (),
        category_line_counts=summarize_category_lines(sections),
        result_fields=collect_result_fields(tree),
        parse_error=None,
    )

def print_audit(result: WorkflowAuditResult, workflow_path: Path) -> None:
    print("SHOPIFY AUTOMATION LAB — SYNC WORKFLOW AUDIT")
    print("=" * 66)
    print("File:", workflow_path.resolve())
    print("Total file lines:", result.metrics.total_file_lines)

    if result.parse_error:
        print("Parse error:", result.parse_error)
        return

    print(
        "Workflow lines:",
        f"{result.metrics.function_start_line}-{result.metrics.function_end_line}",
    )
    print("Workflow size:", result.metrics.function_lines, "lines")
    print("Injected parameters:", result.metrics.parameter_count)
    print("Local assignments:", result.metrics.local_assignment_count)
    print("if branches:", result.metrics.if_count)
    print("for loops:", result.metrics.for_count)
    print("try blocks:", result.metrics.try_count)
    print("raise statements:", result.metrics.raise_count)
    print("return statements:", result.metrics.return_count)

    print("\nWORKFLOW RESULT FIELDS")
    print("-" * 66)
    if result.result_fields:
        for field in result.result_fields:
            print("-", field)
    else:
        print("No SyncWorkflowResult fields detected.")

    print("\nINJECTED DEPENDENCY / PORT USAGE")
    print("-" * 66)
    if result.receiver_usage:
        for usage in result.receiver_usage:
            print(
                f"{usage.receiver}: {usage.call_count} call(s) | "
                + ", ".join(usage.methods)
            )
    else:
        print("No tracked dependency calls detected.")

    print("\nRESPONSIBILITY SECTIONS")
    print("-" * 66)
    for section in result.sections:
        print(
            f"L{section.start_line}-{section.end_line} | "
            f"{section.category:<20} | {section.title}"
        )

    print("\nCATEGORY SIZE SUMMARY")
    print("-" * 66)
    for category, line_count in result.category_line_counts:
        print(f"{category:<20} | {line_count:4d} mapped line(s)")

    print("\nCOHESION / EXTRACTION SIGNALS")
    print("-" * 66)
    signals: list[str] = []

    if result.metrics.function_lines > 500:
        signals.append("The orchestration function is larger than 500 lines.")

    categories = {
        section.category for section in result.sections
        if section.category != "other"
    }
    if len(categories) >= 4:
        signals.append(
            "The workflow coordinates four or more distinct responsibility groups."
        )

    collaborators = {
        usage.receiver for usage in result.receiver_usage
        if usage.receiver != "presenter"
    }
    if len(collaborators) >= 6:
        signals.append(
            "The workflow coordinates six or more non-presentation collaborators."
        )

    if result.metrics.if_count >= 10:
        signals.append(
            "Branching density suggests multiple business sub-workflows."
        )

    if result.metrics.for_count >= 5:
        signals.append(
            "Multiple loops suggest repeated domain-specific processing stages."
        )

    if signals:
        for signal in signals:
            print("-", signal)
    else:
        print("No strong extraction signal detected.")

    print("\nCANDIDATE EXTRACTION ORDER")
    print("-" * 66)
    print("1. Product synchronization + product verification")
    print("2. Inventory alert lifecycle")
    print("3. Order synchronization + order verification")
    print("4. Financial / missing-cost processing")
    print("5. Keep sync_workflow.py as the high-level coordinator")

    print(
        "\nThis audit is read-only. "
        "No Shopify, SQLite, or project state was modified."
    )

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit responsibility boundaries inside "
            "application/sync_workflow.py."
        )
    )
    parser.add_argument("--workflow", type=Path, default=None)
    return parser

def main() -> None:
    args = build_parser().parse_args()
    workflow_path = (
        args.workflow.resolve()
        if args.workflow
        else (
            Path(__file__).resolve().parent.parent
            / "application"
            / "sync_workflow.py"
        )
    )

    if not workflow_path.is_file():
        raise SystemExit(f"sync_workflow.py not found: {workflow_path}")

    print_audit(audit_sync_workflow(workflow_path), workflow_path)

if __name__ == "__main__":
    main()
