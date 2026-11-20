import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from supplier.batch.models import BatchSafetyStatus
from supplier.orchestration.models import (
    SupplierNextAction,
    SupplierOperationsBacklog,
    SupplierSystemPosture,
)
from supplier.orchestration.policy_engine import (
    evaluate_control_plane_policy,
)
from supplier.orchestration.policy_history import (
    SQLiteSupplierPolicyHistoryReader,
)
from supplier.orchestration.policy_models import (
    ControlPlanePolicy,
    OperationalGateReason,
    OperationalGateStatus,
)


def manifest(
    *,
    status=BatchSafetyStatus.EMPTY,
    planned_mutations=0,
    total_delta=0,
):
    return SimpleNamespace(
        status=status,
        planned_mutations=planned_mutations,
        total_absolute_inventory_delta=(
            total_delta
        ),
    )


def evaluate(
    *,
    current_manifest=None,
    backlog=None,
    policy=None,
    consecutive=0,
):
    return evaluate_control_plane_policy(
        manifest=(
            current_manifest
            or manifest()
        ),
        backlog=(
            backlog
            or SupplierOperationsBacklog()
        ),
        policy=(
            policy
            or ControlPlanePolicy()
        ),
        consecutive_human_attention_runs=(
            consecutive
        ),
    )


def test_idle_when_no_work_exists():
    decision = evaluate()

    assert (
        decision.gate_status
        == OperationalGateStatus.IDLE
    )
    assert (
        decision.posture
        == SupplierSystemPosture.IDLE
    )
    assert (
        decision.next_action
        == SupplierNextAction.NONE
    )


def test_safe_batch_requires_approval():
    decision = evaluate(
        current_manifest=manifest(
            status=BatchSafetyStatus.READY,
            planned_mutations=1,
            total_delta=10,
        )
    )

    assert (
        decision.gate_status
        == OperationalGateStatus.APPROVAL_REQUIRED
    )
    assert (
        decision.posture
        == SupplierSystemPosture.READY_FOR_APPROVAL
    )


def test_batch_safety_review_is_preserved():
    decision = evaluate(
        current_manifest=manifest(
            status=BatchSafetyStatus.REVIEW_REQUIRED
        )
    )

    assert (
        decision.gate_status
        == OperationalGateStatus.REVIEW_REQUIRED
    )
    assert (
        OperationalGateReason.BATCH_REVIEW_REQUIRED
        in decision.reasons
    )


def test_batch_safety_block_is_preserved():
    decision = evaluate(
        current_manifest=manifest(
            status=BatchSafetyStatus.BLOCKED
        )
    )

    assert (
        decision.gate_status
        == OperationalGateStatus.BLOCKED
    )
    assert (
        decision.next_action
        == SupplierNextAction.FIX_BLOCKING_ISSUES
    )


def test_human_attention_blocks_new_work():
    decision = evaluate(
        current_manifest=manifest(
            status=BatchSafetyStatus.READY,
            planned_mutations=1,
            total_delta=5,
        ),
        backlog=(
            SupplierOperationsBacklog(
                dead_letter_awaiting_human=1
            )
        ),
    )

    assert (
        decision.posture
        == SupplierSystemPosture.HUMAN_ATTENTION
    )
    assert (
        decision.next_action
        == SupplierNextAction.REVIEW_DEAD_LETTER_CASES
    )


def test_recovery_blocks_new_work():
    decision = evaluate(
        current_manifest=manifest(
            status=BatchSafetyStatus.READY,
            planned_mutations=1,
            total_delta=5,
        ),
        backlog=(
            SupplierOperationsBacklog(
                queued_retry_attempts=1
            )
        ),
    )

    assert (
        decision.posture
        == SupplierSystemPosture.RECOVERY_PENDING
    )


def test_human_attention_outranks_recovery():
    decision = evaluate(
        backlog=(
            SupplierOperationsBacklog(
                queued_retry_attempts=1,
                dead_letter_awaiting_human=1,
            )
        )
    )

    assert (
        decision.posture
        == SupplierSystemPosture.HUMAN_ATTENTION
    )


def test_repeated_human_attention_pauses_supplier():
    decision = evaluate(
        backlog=(
            SupplierOperationsBacklog(
                dead_letter_awaiting_human=1
            )
        ),
        consecutive=3,
    )

    assert (
        decision.gate_status
        == OperationalGateStatus.PAUSED
    )
    assert (
        OperationalGateReason.REPEATED_HUMAN_ATTENTION_PAUSE
        in decision.reasons
    )


def test_pause_does_not_trigger_before_threshold():
    decision = evaluate(
        backlog=(
            SupplierOperationsBacklog(
                dead_letter_awaiting_human=1
            )
        ),
        consecutive=2,
    )

    assert (
        decision.gate_status
        == OperationalGateStatus.BLOCKED
    )


def test_mutation_count_threshold_forces_review():
    policy = ControlPlanePolicy(
        manual_review_mutation_threshold=2
    )

    decision = evaluate(
        policy=policy,
        current_manifest=manifest(
            status=BatchSafetyStatus.READY,
            planned_mutations=3,
            total_delta=10,
        ),
    )

    assert (
        decision.gate_status
        == OperationalGateStatus.REVIEW_REQUIRED
    )
    assert (
        OperationalGateReason.MUTATION_COUNT_REVIEW_THRESHOLD
        in decision.reasons
    )


def test_total_delta_threshold_forces_review():
    policy = ControlPlanePolicy(
        manual_review_total_inventory_delta_threshold=20
    )

    decision = evaluate(
        policy=policy,
        current_manifest=manifest(
            status=BatchSafetyStatus.READY,
            planned_mutations=1,
            total_delta=21,
        ),
    )

    assert (
        decision.gate_status
        == OperationalGateStatus.REVIEW_REQUIRED
    )
    assert (
        OperationalGateReason.INVENTORY_DELTA_REVIEW_THRESHOLD
        in decision.reasons
    )


def test_both_policy_review_reasons_are_preserved():
    policy = ControlPlanePolicy(
        manual_review_mutation_threshold=1,
        manual_review_total_inventory_delta_threshold=5,
    )

    decision = evaluate(
        policy=policy,
        current_manifest=manifest(
            status=BatchSafetyStatus.READY,
            planned_mutations=2,
            total_delta=10,
        ),
    )

    assert len(
        decision.reasons
    ) == 2


def test_policy_fingerprint_is_deterministic():
    first = ControlPlanePolicy()
    second = ControlPlanePolicy()

    assert (
        first.fingerprint
        == second.fingerprint
    )


def test_policy_fingerprint_changes_with_rule():
    first = ControlPlanePolicy()
    second = ControlPlanePolicy(
        manual_review_mutation_threshold=4
    )

    assert (
        first.fingerprint
        != second.fingerprint
    )


def test_invalid_mutation_threshold_is_rejected():
    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        ControlPlanePolicy(
            manual_review_mutation_threshold=0
        )


def test_invalid_pause_threshold_is_rejected():
    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        ControlPlanePolicy(
            pause_after_consecutive_human_attention_runs=0
        )


def test_invalid_boolean_rule_is_rejected():
    with pytest.raises(
        ValueError,
        match="boolean",
    ):
        ControlPlanePolicy(
            block_new_batches_when_human_attention=1
        )


def test_consecutive_input_must_be_non_negative():
    with pytest.raises(
        ValueError,
        match="non-negative integer",
    ):
        evaluate(
            consecutive=-1
        )


def sqlite_factory(connection):
    @contextmanager
    def factory():
        yield connection

    return factory


def test_history_reader_returns_zero_without_table():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    reader = SQLiteSupplierPolicyHistoryReader(
        connection_factory=(
            sqlite_factory(
                connection
            )
        )
    )

    assert (
        reader
        .consecutive_human_attention_runs(
            "demo_supplier"
        )
        == 0
    )


def test_history_reader_counts_consecutive_attention():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    connection.executescript(
        """
        CREATE TABLE supplier_orchestration_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_code TEXT NOT NULL,
            posture TEXT NOT NULL
        );

        INSERT INTO supplier_orchestration_runs (
            supplier_code,
            posture
        )
        VALUES
            ('demo_supplier', 'idle'),
            ('demo_supplier', 'human_attention'),
            ('demo_supplier', 'human_attention');
        """
    )

    reader = SQLiteSupplierPolicyHistoryReader(
        connection_factory=(
            sqlite_factory(
                connection
            )
        )
    )

    assert (
        reader
        .consecutive_human_attention_runs(
            "demo_supplier"
        )
        == 2
    )


def test_history_reader_stops_at_latest_non_attention():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    connection.executescript(
        """
        CREATE TABLE supplier_orchestration_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_code TEXT NOT NULL,
            posture TEXT NOT NULL
        );

        INSERT INTO supplier_orchestration_runs (
            supplier_code,
            posture
        )
        VALUES
            ('demo_supplier', 'human_attention'),
            ('demo_supplier', 'human_attention'),
            ('demo_supplier', 'idle');
        """
    )

    reader = SQLiteSupplierPolicyHistoryReader(
        connection_factory=(
            sqlite_factory(
                connection
            )
        )
    )

    assert (
        reader
        .consecutive_human_attention_runs(
            "demo_supplier"
        )
        == 0
    )


def test_history_reader_is_supplier_specific():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    connection.executescript(
        """
        CREATE TABLE supplier_orchestration_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_code TEXT NOT NULL,
            posture TEXT NOT NULL
        );

        INSERT INTO supplier_orchestration_runs (
            supplier_code,
            posture
        )
        VALUES
            ('supplier_a', 'human_attention'),
            ('supplier_b', 'idle'),
            ('supplier_a', 'human_attention');
        """
    )

    reader = SQLiteSupplierPolicyHistoryReader(
        connection_factory=(
            sqlite_factory(
                connection
            )
        )
    )

    assert (
        reader
        .consecutive_human_attention_runs(
            "supplier_a"
        )
        == 2
    )


def test_human_attention_block_can_be_disabled():
    policy = ControlPlanePolicy(
        block_new_batches_when_human_attention=False
    )

    decision = evaluate(
        policy=policy,
        current_manifest=manifest(
            status=BatchSafetyStatus.EMPTY
        ),
        backlog=(
            SupplierOperationsBacklog(
                dead_letter_awaiting_human=1
            )
        ),
    )

    assert (
        decision.posture
        == SupplierSystemPosture.IDLE
    )


def test_recovery_block_can_be_disabled():
    policy = ControlPlanePolicy(
        block_new_batches_when_recovery_pending=False
    )

    decision = evaluate(
        policy=policy,
        current_manifest=manifest(
            status=BatchSafetyStatus.EMPTY
        ),
        backlog=(
            SupplierOperationsBacklog(
                queued_retry_attempts=1
            )
        ),
    )

    assert (
        decision.posture
        == SupplierSystemPosture.IDLE
    )
