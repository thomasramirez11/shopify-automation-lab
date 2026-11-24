"""V2.8B/9 offline risk-budget exercise. NO Shopify client or project DB."""
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.supplier_batch_recovery_synthetic_demo import FakeReadback, build_prepared  # noqa: E402
from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository  # noqa: E402
from supplier.batch.live_readonly_archive import ReadOnlyRecoveryArchive  # noqa: E402
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository  # noqa: E402
from supplier.batch.live_recovery_service import SupplierLiveBatchRecoveryService  # noqa: E402
from supplier.batch.live_risk_budget import (  # noqa: E402
    RiskStatus, ControlledTestBudget, assess_test_operation,
)


@contextmanager
def isolated_case(path):
    db = sqlite3.connect(path)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    print("SHOPIFY AUTOMATION LAB — V2.8B/9 OPERATION RISK BUDGET")
    print("MODE: OFFLINE / SYNTHETIC INVENTORY / TEMPORARY SQLITE")
    with TemporaryDirectory(prefix="v2-8b9-") as directory:
        file = Path(directory) / "test_only.sqlite3"
        prepared = build_prepared()
        connection = lambda: isolated_case(file)
        service = SupplierLiveBatchRecoveryService(
            intent_repository=SupplierLiveBatchIntentRepository(connection_factory=connection),
            recovery_repository=SupplierLiveBatchRecoveryRepository(connection_factory=connection),
        )
        service.prepare(prepared)
        archive = ReadOnlyRecoveryArchive(file)
        budget = ControlledTestBudget(
            store_domain="demo-test.myshopify.com",
            location_id=prepared.location_id,
            sku_inventory_items=(
                ("DEMO-1001", "gid://shopify/InventoryItem/1001"),
                ("DEMO-1002", "gid://shopify/InventoryItem/1002"),
            ),
        )
        options = dict(
            archive=archive, operation_id=prepared.preview.operation_id,
            expected_plan_fingerprint=prepared.plan_fingerprint,
            expected_manifest_fingerprint=prepared.manifest_fingerprint,
            observed_store_domain=budget.store_domain,
            proposal_source="CONTROLLED_TEST_SYNTHETIC", budget=budget,
        )
        checks = (
            ("IN_SCOPE", {}, FakeReadback({"1001": 25, "1002": 40}), RiskStatus.REVIEW_OK_FOR_FURTHER_DESIGN),
            ("WRONG_STORE", {"observed_store_domain": "other-test.myshopify.com"}, FakeReadback({"1001": 25, "1002": 40}), RiskStatus.STORE_MISMATCH),
            ("EXCESSIVE_DELTA", {"budget": replace(budget, max_delta_per_item=1)}, FakeReadback({"1001": 25, "1002": 40}), RiskStatus.RISK_BUDGET_EXCEEDED),
            ("SUPPLIER_FEED_NOT_ATTESTED", {"proposal_source": "SUPPLIER_FEED"}, FakeReadback({"1001": 25, "1002": 40}), RiskStatus.SOURCE_NOT_ALLOWED),
            ("DRIFT", {}, FakeReadback({"1001": 25, "1002": 39}), RiskStatus.REVIEW_BLOCKED),
        )
        for label, overrides, port, expected in checks:
            result = assess_test_operation(**{**options, **overrides}, readback_port=port)
            assert result.status is expected, (label, result.status, expected)
            assert not result.live_execution_allowed and not result.automatic_retry_allowed
            print(f"CASE {label}: {result.status.value}")
        print("LIVE EXECUTION ALLOWED: False")
        print("AUTOMATIC RETRY ALLOWED: False")
        print("REAL SHOPIFY NETWORK CALLS: 0")
        print("LIVE SHOPIFY WRITES: 0")
        print("PROJECT SQLITE WRITES: 0")
        print("STATUS: TEST RISK BUDGET VERIFIED — LIVE SENDER DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
