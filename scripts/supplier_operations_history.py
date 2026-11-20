from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from supplier.orchestration.bootstrap import SUPPLIER_CODE  # noqa: E402
from supplier.orchestration.run_models import policy_version_label  # noqa: E402
from supplier.orchestration.run_repository import SupplierOrchestrationRunRepository  # noqa: E402


def _operational(run) -> str:
    if run.previous_run_id is None:
        return "INITIAL"
    if run.posture_changed and run.next_action_changed:
        return "POSTURE_AND_ACTION_CHANGED"
    if run.posture_changed:
        return "POSTURE_CHANGED"
    if run.next_action_changed:
        return "ACTION_CHANGED"
    return "UNCHANGED"


def _configuration(run) -> str:
    if run.previous_run_id is None:
        return "INITIAL"
    if (
        run.policy_changed
        and not run.manifest_changed
        and not (run.previous_policy_fingerprint or "")
        and run.policy_fingerprint
    ):
        return "POLICY_PROVENANCE_ESTABLISHED"
    if run.policy_changed and run.manifest_changed:
        return "POLICY_AND_MANIFEST_CHANGED"
    if run.policy_changed:
        return "POLICY_CHANGED"
    if run.manifest_changed:
        return "MANIFEST_CHANGED"
    return "UNCHANGED"


def main() -> int:
    repository = SupplierOrchestrationRunRepository()
    repository.ensure_schema()
    runs = repository.get_recent(supplier_code=SUPPLIER_CODE, limit=20)

    print("SHOPIFY AUTOMATION LAB — V2.7 CONTROL-PLANE HISTORY")
    print("=" * 72)
    print("LEDGER MODE: APPEND ONLY")
    print(f"Supplier: {SUPPLIER_CODE}")
    print(f"Runs stored: {repository.count_runs(SUPPLIER_CODE)}")
    print("-" * 72)

    if not runs:
        print("No orchestration runs recorded yet.")
        return 0

    for run in runs:
        print(f"Run #{run.run_id}")
        print(f"  Posture: {run.posture.upper()}")
        print(f"  Next action: {run.next_action.upper()}")
        print(f"  Operational transition: {_operational(run)}")
        print(f"  Configuration transition: {_configuration(run)}")
        print(f"  Snapshot changed: {bool(run.snapshot_changed)}")
        print(f"  Policy version: {policy_version_label(run.policy_fingerprint)}")
        print(f"  Previous run: {run.previous_run_id}")
        print(f"  Planned mutations: {run.planned_mutations}")
        print(f"  DLQ awaiting human: {run.dead_letter_awaiting_human}")
        print(f"  DLQ acknowledged: {run.dead_letter_acknowledged}")
        print(f"  Closed resolutions: {run.resolution_closed}")
        print(f"  Recorded: {run.created_at}")
        print("-" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
