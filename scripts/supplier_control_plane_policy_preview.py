from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


from supplier.orchestration.bootstrap import (  # noqa: E402
    CONTROL_PLANE_POLICY,
    build_default_supplier_operations_orchestrator,
)


def main() -> int:
    snapshot = (
        build_default_supplier_operations_orchestrator(
            PROJECT_ROOT
        )
        .build_snapshot()
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 CONTROL-PLANE POLICY ENGINE"
    )
    print("=" * 72)
    print(
        "MODE: READ ONLY POLICY EVALUATION"
    )
    print(
        "LIVE SHOPIFY EXECUTION: DISABLED"
    )
    print("-" * 72)

    print(
        "ACTIVE POLICY"
    )
    print("-" * 72)
    print(
        "Block new batches during human attention: "
        f"{CONTROL_PLANE_POLICY.block_new_batches_when_human_attention}"
    )
    print(
        "Block new batches during recovery: "
        f"{CONTROL_PLANE_POLICY.block_new_batches_when_recovery_pending}"
    )
    print(
        "Manual review mutation threshold: "
        f"{CONTROL_PLANE_POLICY.manual_review_mutation_threshold}"
    )
    print(
        "Manual review total inventory delta threshold: "
        f"{CONTROL_PLANE_POLICY.manual_review_total_inventory_delta_threshold}"
    )
    print(
        "Pause after consecutive HUMAN_ATTENTION runs: "
        f"{CONTROL_PLANE_POLICY.pause_after_consecutive_human_attention_runs}"
    )
    print(
        "Policy fingerprint:"
    )
    print(
        snapshot.policy_fingerprint
    )
    print("-" * 72)

    print(
        "CURRENT POLICY DECISION"
    )
    print("-" * 72)
    print(
        f"Gate status: "
        f"{snapshot.policy_gate_status.upper()}"
    )
    print(
        "Reasons: "
        + ", ".join(
            snapshot.policy_reasons
        )
    )
    print(
        "Consecutive HUMAN_ATTENTION runs: "
        f"{snapshot.consecutive_human_attention_runs}"
    )
    print(
        f"System posture: "
        f"{snapshot.posture.value.upper()}"
    )
    print(
        f"Next allowed action: "
        f"{snapshot.next_action.value.upper()}"
    )
    print(
        f"Planned mutations: "
        f"{snapshot.plan.planned_mutations}"
    )
    print(
        "Total absolute inventory delta: "
        f"{snapshot.manifest.total_absolute_inventory_delta}"
    )
    print("-" * 72)

    print(
        "Orchestration fingerprint:"
    )
    print(
        snapshot.orchestration_fingerprint
    )
    print()
    print(
        "SHOPIFY WRITES PERFORMED: 0"
    )
    print(
        "SQLITE WRITES PERFORMED: 0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
