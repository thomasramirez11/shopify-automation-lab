from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from supplier.orchestration.bootstrap import SUPPLIER_CODE  # noqa: E402
from supplier.orchestration.run_repository import SupplierOrchestrationRunRepository  # noqa: E402


def main() -> int:
    repository = SupplierOrchestrationRunRepository()
    repository.ensure_schema()
    runs = repository.get_recent(supplier_code=SUPPLIER_CODE, limit=20)

    print('SHOPIFY AUTOMATION LAB — V2.7 CONTROL-PLANE HISTORY')
    print('=' * 72)
    print('LEDGER MODE: APPEND ONLY')
    print(f'Supplier: {SUPPLIER_CODE}')
    print(f'Runs stored: {repository.count_runs(SUPPLIER_CODE)}')
    print('-' * 72)

    if not runs:
        print('No orchestration runs recorded yet.')
        return 0

    for run in runs:
        if run.previous_run_id is None:
            transition = 'INITIAL'
        elif run.posture_changed and run.next_action_changed:
            transition = 'POSTURE_AND_ACTION_CHANGED'
        elif run.posture_changed:
            transition = 'POSTURE_CHANGED'
        elif run.next_action_changed:
            transition = 'ACTION_CHANGED'
        else:
            transition = 'UNCHANGED'

        print(f'Run #{run.run_id}')
        print(f'  Posture: {run.posture.upper()}')
        print(f'  Next action: {run.next_action.upper()}')
        print(f'  Transition: {transition}')
        print(f'  Previous run: {run.previous_run_id}')
        print(f'  Planned mutations: {run.planned_mutations}')
        print(f'  DLQ awaiting human: {run.dead_letter_awaiting_human}')
        print(f'  DLQ acknowledged: {run.dead_letter_acknowledged}')
        print(f'  Closed resolutions: {run.resolution_closed}')
        print(f'  Recorded: {run.created_at}')
        print('-' * 72)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
