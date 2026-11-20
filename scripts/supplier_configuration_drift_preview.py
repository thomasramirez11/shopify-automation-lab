from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from supplier.orchestration.bootstrap import SUPPLIER_CODE  # noqa: E402
from supplier.orchestration.run_models import policy_version_label  # noqa: E402
from supplier.orchestration.run_repository import SupplierOrchestrationRunRepository  # noqa: E402


def main() -> int:
    repository = SupplierOrchestrationRunRepository()
    repository.ensure_schema()
    runs = repository.get_recent(supplier_code=SUPPLIER_CODE, limit=2)

    print("SHOPIFY AUTOMATION LAB — V2.7 CONFIGURATION DRIFT PREVIEW")
    print("=" * 72)
    print("MODE: READ ONLY CONFIGURATION PROVENANCE")
    print("-" * 72)

    if not runs:
        print("No orchestration runs recorded yet.")
        return 0

    current = runs[0]
    print(f"Current run: #{current.run_id}")
    print(f"Operational posture: {current.posture.upper()}")
    print(f"Policy version: {policy_version_label(current.policy_fingerprint)}")
    print(f"Policy changed from previous run: {bool(current.policy_changed)}")
    print(f"Manifest changed from previous run: {bool(current.manifest_changed)}")
    print(f"Whole snapshot changed: {bool(current.snapshot_changed)}")
    if current.previous_run_id is None:
        print("Previous run: NONE")
    else:
        print(f"Previous run: #{current.previous_run_id}")
        print(f"Previous policy version: {policy_version_label(current.previous_policy_fingerprint or '')}")
    print("-" * 72)
    if (
        current.policy_changed
        and not current.manifest_changed
        and not (current.previous_policy_fingerprint or "")
        and current.policy_fingerprint
    ):
        classification = "POLICY_PROVENANCE_ESTABLISHED"
    elif current.policy_changed:
        classification = "POLICY_CHANGED"
    elif current.manifest_changed:
        classification = "MANIFEST_CHANGED"
    elif current.snapshot_changed:
        classification = "STATE_ONLY_CHANGED"
    else:
        classification = "UNCHANGED"
    print(f"DRIFT CLASSIFICATION: {classification}")
    print()
    print("SHOPIFY WRITES PERFORMED: 0")
    print("SQLITE WRITES PERFORMED: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
