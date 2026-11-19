from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from supplier.orchestration.bootstrap import build_default_supplier_operations_orchestrator  # noqa: E402
from supplier.orchestration.run_repository import SupplierOrchestrationRunRepository  # noqa: E402
from supplier.orchestration.run_service import SupplierOrchestrationRunService  # noqa: E402


def main() -> int:
    snapshot = build_default_supplier_operations_orchestrator(PROJECT_ROOT).build_snapshot()
    repository = SupplierOrchestrationRunRepository()
    result = SupplierOrchestrationRunService(repository).record_snapshot(snapshot)
    run = result.run

    print('SHOPIFY AUTOMATION LAB — V2.7 CONTROL-PLANE RUN LEDGER')
    print('=' * 72)
    print('MODE: READ + AUDIT')
    print('LIVE SHOPIFY EXECUTION: DISABLED')
    print('SQLITE BUSINESS WRITES: 0')
    print('SQLITE AUDIT WRITES: 1')
    print('-' * 72)
    print(f'Run ID: #{run.run_id}')
    print(f'Supplier: {run.supplier_code}')
    print(f'Posture: {run.posture.upper()}')
    print(f'Next action: {run.next_action.upper()}')
    print(f'Transition: {result.transition_type.value.upper()}')
    if run.previous_run_id is None:
        print('Previous run: NONE')
    else:
        print(f'Previous run: #{run.previous_run_id}')
        print(f'Previous posture: {run.previous_posture.upper()}')
    print(f'Posture changed: {bool(run.posture_changed)}')
    print(f'Next action changed: {bool(run.next_action_changed)}')
    print('-' * 72)
    print(f'Planned mutations: {run.planned_mutations}')
    print(f'Queued retries: {run.queued_retry_attempts}')
    print(f'DLQ awaiting human: {run.dead_letter_awaiting_human}')
    print(f'DLQ acknowledged: {run.dead_letter_acknowledged}')
    print(f'Closed resolutions: {run.resolution_closed}')
    print('-' * 72)
    print('Snapshot fingerprint:')
    print(run.orchestration_fingerprint)
    print(f'Total recorded runs: {repository.count_runs(run.supplier_code)}')
    print('SHOPIFY WRITES PERFORMED: 0')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
