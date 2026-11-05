
import ast

from scripts.sync_workflow_audit import (
    audit_sync_workflow,
    categorize_section,
    collect_result_fields,
    extract_sections,
    normalize_section_title,
    summarize_category_lines,
)

def test_normalize_numbered_heading():
    assert normalize_section_title(
        "10B. Keep low-inventory alerts synchronized"
    ) == "Keep low-inventory alerts synchronized"

def test_product_heading_category():
    assert categorize_section(
        "Retrieve products from Shopify"
    ) == "product_sync"

def test_inventory_heading_category_wins_over_product():
    assert categorize_section(
        "Keep low-inventory alerts synchronized"
    ) == "inventory_alerts"

def test_order_heading_category():
    assert categorize_section(
        "Persist Shopify orders and detect new orders"
    ) == "order_sync"

def test_financial_heading_category_wins_over_order():
    assert categorize_section(
        "Automatically process order finances"
    ) == "financial_processing"

def test_verification_heading_category_wins_over_product():
    assert categorize_section(
        "Verify product database state"
    ) == "verification"

def test_sync_audit_heading_category():
    assert categorize_section(
        "Mark synchronization successful"
    ) == "sync_audit"

def test_extract_sections_returns_ranges():
    source = """
def run_synchronization_workflow():
    # 6. Retrieve products from Shopify
    products = []

    # 7. Persist Shopify products into SQLite
    saved = True
""".lstrip()
    sections = extract_sections(source)
    assert len(sections) == 2
    assert sections[0].title == "Retrieve products from Shopify"
    assert sections[0].start_line < sections[0].end_line

def test_category_line_summary():
    source = """
def run_synchronization_workflow():
    # 6. Retrieve products from Shopify
    products = []

    # 7. Persist Shopify products into SQLite
    saved = True

    # 8. Retrieve orders from Shopify
    orders = []
""".lstrip()
    summary = dict(summarize_category_lines(extract_sections(source)))
    assert summary["product_sync"] > 0
    assert summary["order_sync"] > 0

def test_result_field_detection():
    tree = ast.parse("""
from dataclasses import dataclass
@dataclass(frozen=True)
class SyncWorkflowResult:
    products_seen: int
    orders_seen: int
""")
    assert collect_result_fields(tree) == ("products_seen", "orders_seen")

def test_audit_detects_dependency_method_calls(tmp_path):
    path = tmp_path / "sync_workflow.py"
    path.write_text("""
from dataclasses import dataclass
@dataclass(frozen=True)
class SyncWorkflowResult:
    products_seen: int

def run_synchronization_workflow(*, product_service, product_repository, presenter):
    products = product_service.get_all_products()
    product_repository.save_product(products[0])
    presenter.show_product_retrieval_result(products)
    return SyncWorkflowResult(products_seen=len(products))
""".lstrip(), encoding="utf-8")
    result = audit_sync_workflow(path)
    usage = {item.receiver: item for item in result.receiver_usage}
    assert usage["product_service"].call_count == 1
    assert "get_all_products" in usage["product_service"].methods
    assert "save_product" in usage["product_repository"].methods
    assert "show_product_retrieval_result" in usage["presenter"].methods

def test_audit_counts_control_flow(tmp_path):
    path = tmp_path / "sync_workflow.py"
    path.write_text("""
def run_synchronization_workflow(*, items):
    for item in items:
        if item:
            pass
    if not items:
        raise RuntimeError("empty")
    return len(items)
""".lstrip(), encoding="utf-8")
    result = audit_sync_workflow(path)
    assert result.metrics.for_count == 1
    assert result.metrics.if_count == 2
    assert result.metrics.raise_count == 1
    assert result.metrics.return_count == 1

def test_audit_counts_keyword_only_parameters(tmp_path):
    path = tmp_path / "sync_workflow.py"
    path.write_text("""
def run_synchronization_workflow(*, one, two, three):
    return None
""".lstrip(), encoding="utf-8")
    result = audit_sync_workflow(path)
    assert result.metrics.parameter_count == 3

def test_audit_reports_parse_error_without_execution(tmp_path):
    path = tmp_path / "sync_workflow.py"
    path.write_text("def run_synchronization_workflow(:\n", encoding="utf-8")
    result = audit_sync_workflow(path)
    assert result.parse_error is not None
    assert result.metrics.total_file_lines == 1

def test_audit_is_static_and_does_not_execute_workflow(tmp_path):
    path = tmp_path / "sync_workflow.py"
    path.write_text("""
def run_synchronization_workflow():
    raise RuntimeError("this must never execute during audit")
""".lstrip(), encoding="utf-8")
    result = audit_sync_workflow(path)
    assert result.parse_error is None
    assert result.metrics.raise_count == 1
