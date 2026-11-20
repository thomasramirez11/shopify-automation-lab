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
    SUPPLIER_CODE,
    build_default_supplier_operations_orchestrator,
)
from supplier.orchestration.health_engine import (  # noqa: E402
    evaluate_control_plane_health,
)
from supplier.orchestration.health_policy import (  # noqa: E402
    DEFAULT_CONTROL_PLANE_SLO_POLICY,
)
from supplier.orchestration.run_repository import (  # noqa: E402
    SupplierOrchestrationRunRepository,
)


HEALTH_POLICY = (
    DEFAULT_CONTROL_PLANE_SLO_POLICY
)


def main() -> int:
    snapshot = (
        build_default_supplier_operations_orchestrator(
            PROJECT_ROOT
        )
        .build_snapshot()
    )

    repository = (
        SupplierOrchestrationRunRepository()
    )

    recent_runs = repository.get_recent(
        supplier_code=SUPPLIER_CODE,
        limit=(
            HEALTH_POLICY
            .history_window_runs
        ),
    )

    report = evaluate_control_plane_health(
        snapshot=snapshot,
        recent_runs=recent_runs,
        policy=HEALTH_POLICY,
    )

    print(
        "SHOPIFY AUTOMATION LAB — "
        "V2.7 CONTROL-PLANE HEALTH + SLOs"
    )
    print("=" * 72)
    print(
        "MODE: READ ONLY HEALTH EVALUATION"
    )
    print(
        "LIVE SHOPIFY EXECUTION: DISABLED"
    )
    print("-" * 72)

    print(
        "HEALTH SUMMARY"
    )
    print("-" * 72)
    print(
        f"Supplier: "
        f"{report.supplier_code}"
    )
    print(
        f"Health status: "
        f"{report.status.value.upper()}"
    )
    print(
        f"Health score: "
        f"{report.score}/100"
    )
    print(
        f"SLO compliance: "
        f"{report.slo_compliance_percentage:.1f}% "
        f"({report.slos_met}/{report.slo_count})"
    )
    print(
        "Reasons: "
        + ", ".join(
            reason.value
            for reason in report.reasons
        )
    )
    print("-" * 72)

    print(
        "RELIABILITY WINDOW"
    )
    print("-" * 72)
    print(
        f"Recent runs evaluated: "
        f"{report.history_runs_evaluated}"
    )
    print(
        f"Healthy runs: "
        f"{report.healthy_runs}"
    )
    print(
        f"Healthy run percentage: "
        f"{report.healthy_run_percentage:.1f}%"
    )
    print(
        f"Consecutive healthy runs: "
        f"{report.consecutive_healthy_runs}"
    )
    print(
        f"Unresolved human cases: "
        f"{report.unresolved_human_cases}"
    )
    print(
        f"Queued retry attempts: "
        f"{report.queued_retry_attempts}"
    )
    print("-" * 72)

    print(
        "SLO CHECKS"
    )
    print("-" * 72)

    for check in report.slo_checks:
        print(
            f"{check.name}: "
            f"{'PASS' if check.met else 'FAIL'} "
            f"| observed={check.observed} "
            f"| target={check.target}"
        )

    print("-" * 72)
    print(
        "Health/SLO policy fingerprint:"
    )
    print(
        report.slo_policy_fingerprint
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
