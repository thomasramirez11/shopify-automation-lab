from __future__ import annotations

from pathlib import Path

from supplier.adapters.json_file_supplier import JsonFileSupplierAdapter
from supplier.batch.models import BatchSafetyPolicy
from supplier.comparison.snapshot import SQLiteShopifyComparisonSnapshotAdapter
from supplier.decision.models import InventorySyncPolicy
from supplier.mapping.json_loader import JsonSupplierMappingLoader
from supplier.orchestration.backlog import SQLiteSupplierOperationsBacklogReader
from supplier.orchestration.orchestrator import SupplierOperationsOrchestrator

SUPPLIER_CODE = 'demo_supplier'
ITEM_POLICY = InventorySyncPolicy(max_inventory_delta=50)
BATCH_POLICY = BatchSafetyPolicy(
    max_mutations_per_batch=5,
    max_total_absolute_inventory_delta=100,
    max_single_item_absolute_delta=50,
)


def build_default_supplier_operations_orchestrator(project_root: Path) -> SupplierOperationsOrchestrator:
    return SupplierOperationsOrchestrator(
        supplier_code=SUPPLIER_CODE,
        supplier_adapter=JsonFileSupplierAdapter(
            project_root / 'supplier' / 'samples' / 'sample_supplier_feed.json'
        ),
        mapping_loader=JsonSupplierMappingLoader(
            project_root / 'supplier' / 'samples' / 'sample_supplier_mappings.json'
        ),
        snapshot_adapter=SQLiteShopifyComparisonSnapshotAdapter(),
        item_policy=ITEM_POLICY,
        batch_policy=BATCH_POLICY,
        backlog_reader=SQLiteSupplierOperationsBacklogReader(),
    )
