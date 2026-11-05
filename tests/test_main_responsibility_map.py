from pathlib import Path

from scripts.main_responsibility_map import (
    build_responsibility_map,
    categorize_section,
    collect_metrics,
    extract_sections,
    group_sections,
    normalize_section_title,
)


def test_normalize_numbered_section():
    assert (
        normalize_section_title(
            "10B. Keep low-inventory alerts synchronized"
        )
        == "Keep low-inventory alerts synchronized"
    )


def test_categorize_shopify_authentication():
    assert (
        categorize_section(
            "Authenticate with Shopify"
        )
        == "shopify_connection"
    )


def test_categorize_product_flow():
    assert (
        categorize_section(
            "Persist Shopify products into SQLite"
        )
        == "product_flow"
    )


def test_categorize_order_flow():
    assert (
        categorize_section(
            "Create persistent alerts for new orders"
        )
        == "order_flow"
    )


def test_categorize_financial_flow():
    assert (
        categorize_section(
            "Display financial analysis"
        )
        == "financial_flow"
    )


def test_categorize_reporting():
    assert (
        categorize_section(
            "Generate and save daily report"
        )
        == "reporting"
    )


def test_extract_sections_returns_line_ranges():
    source = """
def main():
    # 1. Create Shopify client
    client = object()

    # 2. Authenticate with Shopify
    client.authenticate()
""".lstrip()

    sections = extract_sections(
        source
    )

    assert len(sections) == 2

    assert (
        sections[0].title
        == "Create Shopify client"
    )

    assert (
        sections[0].start_line
        < sections[0].end_line
    )


def test_collect_metrics_finds_main_size():
    source = """
def main():
    print("hello")
    print("world")
""".lstrip()

    metrics = collect_metrics(
        source
    )

    assert metrics.main_start_line == 1
    assert metrics.main_end_line == 3
    assert metrics.main_body_lines == 3
    assert metrics.print_calls == 2


def test_collect_metrics_finds_logger_calls():
    source = """
def main():
    logger.info("start")
    logger.error("failed")
""".lstrip()

    metrics = collect_metrics(
        source
    )

    assert metrics.logger_calls == 2


def test_collect_metrics_finds_try_and_except():
    source = """
def main():
    try:
        do_work()
    except Exception:
        recover()
""".lstrip()

    metrics = collect_metrics(
        source
    )

    assert metrics.try_blocks == 1
    assert metrics.except_handlers == 1


def test_collect_metrics_finds_dependency_constructors():
    source = """
def main():
    client = ShopifyClient()
    repo = ProductRepository()
    service = ProductService(client)
""".lstrip()

    metrics = collect_metrics(
        source
    )

    assert metrics.constructor_calls == (
        "ProductRepository",
        "ProductService",
        "ShopifyClient",
    )


def test_collect_metrics_finds_environment_reads():
    source = """
import os

def main():
    os.getenv("TEST_FLAG")
""".lstrip()

    metrics = collect_metrics(
        source
    )

    assert metrics.environment_reads == (
        "TEST_FLAG",
    )


def test_group_sections_organizes_categories():
    source = """
def main():
    # 1. Create Shopify client
    client = object()

    # 2. Retrieve products from Shopify
    products = []

    # 3. Display financial analysis
    summary = {}
""".lstrip()

    sections = tuple(
        extract_sections(
            source
        )
    )

    grouped = group_sections(
        sections
    )

    assert "shopify_connection" in grouped
    assert "product_flow" in grouped
    assert "financial_flow" in grouped


def test_build_map_reports_parse_error_without_execution(
    tmp_path,
):
    main_path = (
        tmp_path
        / "main.py"
    )

    main_path.write_text(
        "def main(:\n",
        encoding="utf-8",
    )

    result = build_responsibility_map(
        main_path
    )

    assert result.parse_error is not None
    assert result.metrics.total_lines == 1


def test_build_map_reads_real_file_without_running_it(
    tmp_path,
):
    main_path = (
        tmp_path
        / "main.py"
    )

    main_path.write_text(
        """
def main():
    # 1. Create Shopify client
    raise RuntimeError("must never execute")
""".lstrip(),
        encoding="utf-8",
    )

    result = build_responsibility_map(
        main_path
    )

    assert result.parse_error is None
    assert len(result.sections) == 1
