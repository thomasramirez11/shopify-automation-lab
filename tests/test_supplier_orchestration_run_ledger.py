import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from database.supplier_orchestration_schema import ensure_supplier_orchestration_schema
from supplier.orchestration.models import SupplierNextAction, SupplierOperationsBacklog, SupplierSystemPosture
from supplier.orchestration.run_models import OrchestrationTransitionType
from supplier.orchestration.run_repository import SupplierOrchestrationRunRepository
from supplier.orchestration.run_service import SupplierOrchestrationRunService


def make_factory():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    @contextmanager
    def factory():
        try:
            yield connection
        finally:
            connection.commit()
    return connection, factory


def snap(*, supplier='demo_supplier', posture=SupplierSystemPosture.HUMAN_ATTENTION,
         action=SupplierNextAction.REVIEW_DEAD_LETTER_CASES, fingerprint='a'*64,
         manifest='b'*64, planned=0, queued=0, awaiting=1, acknowledged=1, closed=1):
    return SimpleNamespace(
        supplier_code=supplier,
        orchestration_fingerprint=fingerprint,
        posture=posture,
        next_action=action,
        manifest=SimpleNamespace(manifest_fingerprint=manifest),
        plan=SimpleNamespace(planned_mutations=planned, review_items=0, blocked_items=0, no_action_items=2),
        backlog=SupplierOperationsBacklog(
            queued_retry_attempts=queued,
            dead_letter_awaiting_human=awaiting,
            dead_letter_acknowledged=acknowledged,
            resolution_closed=closed,
        ),
    )


def repo(factory):
    return SupplierOrchestrationRunRepository(connection_factory=factory)


def svc(factory):
    r = repo(factory)
    return r, SupplierOrchestrationRunService(r)


def test_schema_creates_table():
    c, _ = make_factory(); ensure_supplier_orchestration_schema(c)
    assert c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='supplier_orchestration_runs';").fetchone()


def test_schema_idempotent():
    c, _ = make_factory(); ensure_supplier_orchestration_schema(c); ensure_supplier_orchestration_schema(c)


def test_update_blocked():
    c, f = make_factory(); _, s = svc(f); s.record_snapshot(snap())
    with pytest.raises(sqlite3.IntegrityError, match='append-only'):
        c.execute("UPDATE supplier_orchestration_runs SET posture='idle';")


def test_delete_blocked():
    c, f = make_factory(); _, s = svc(f); s.record_snapshot(snap())
    with pytest.raises(sqlite3.IntegrityError, match='append-only'):
        c.execute('DELETE FROM supplier_orchestration_runs;')


def test_first_run_initial():
    _, f = make_factory(); _, s = svc(f); result = s.record_snapshot(snap())
    assert result.transition_type == OrchestrationTransitionType.INITIAL
    assert result.run.previous_run_id is None


def test_identical_second_run_unchanged():
    _, f = make_factory(); r, s = svc(f); first = s.record_snapshot(snap()); second = s.record_snapshot(snap())
    assert second.transition_type == OrchestrationTransitionType.UNCHANGED
    assert second.run.previous_run_id == first.run.run_id
    assert r.count_runs('demo_supplier') == 2


def test_same_fingerprint_repeated_allowed():
    _, f = make_factory(); r, s = svc(f); s.record_snapshot(snap(fingerprint='c'*64)); s.record_snapshot(snap(fingerprint='c'*64))
    assert r.count_runs('demo_supplier') == 2


def test_posture_and_action_transition():
    _, f = make_factory(); _, s = svc(f); s.record_snapshot(snap())
    result = s.record_snapshot(snap(posture=SupplierSystemPosture.IDLE, action=SupplierNextAction.NONE,
                                    fingerprint='c'*64, awaiting=0, acknowledged=0, closed=3))
    assert result.transition_type == OrchestrationTransitionType.POSTURE_AND_ACTION_CHANGED
    assert result.run.previous_posture == 'human_attention'
    assert result.run.posture_changed == 1 and result.run.next_action_changed == 1


def test_posture_only_transition():
    _, f = make_factory(); _, s = svc(f)
    s.record_snapshot(snap(posture=SupplierSystemPosture.REVIEW_REQUIRED, action=SupplierNextAction.REVIEW_BATCH))
    result = s.record_snapshot(snap(posture=SupplierSystemPosture.BLOCKED, action=SupplierNextAction.REVIEW_BATCH, fingerprint='c'*64))
    assert result.transition_type == OrchestrationTransitionType.POSTURE_CHANGED


def test_action_only_transition():
    _, f = make_factory(); _, s = svc(f)
    s.record_snapshot(snap(posture=SupplierSystemPosture.REVIEW_REQUIRED, action=SupplierNextAction.REVIEW_BATCH))
    result = s.record_snapshot(snap(posture=SupplierSystemPosture.REVIEW_REQUIRED, action=SupplierNextAction.FIX_BLOCKING_ISSUES, fingerprint='c'*64))
    assert result.transition_type == OrchestrationTransitionType.ACTION_CHANGED


def test_latest_newest():
    _, f = make_factory(); r, s = svc(f); a=s.record_snapshot(snap()); b=s.record_snapshot(snap(fingerprint='c'*64))
    assert r.get_latest('demo_supplier').run_id == b.run.run_id != a.run.run_id


def test_recent_newest_first():
    _, f=make_factory(); r,s=svc(f); a=s.record_snapshot(snap()); b=s.record_snapshot(snap(fingerprint='c'*64))
    assert [x.run_id for x in r.get_recent(supplier_code='demo_supplier', limit=2)] == [b.run.run_id,a.run.run_id]


def test_supplier_histories_isolated():
    _, f=make_factory(); r,s=svc(f); s.record_snapshot(snap(supplier='a')); s.record_snapshot(snap(supplier='b'))
    assert r.count_runs('a')==1 and r.count_runs('b')==1


def test_counts_persisted():
    _, f=make_factory(); _,s=svc(f); run=s.record_snapshot(snap(planned=2,queued=1,awaiting=3,acknowledged=4,closed=5)).run
    assert (run.planned_mutations,run.queued_retry_attempts,run.dead_letter_awaiting_human,run.dead_letter_acknowledged,run.resolution_closed)==(2,1,3,4,5)


def test_fingerprints_preserved():
    _, f=make_factory(); _,s=svc(f); run=s.record_snapshot(snap(fingerprint='d'*64,manifest='e'*64)).run
    assert run.orchestration_fingerprint=='d'*64 and run.manifest_fingerprint=='e'*64


def test_limit_validation():
    _, f=make_factory(); r=repo(f)
    with pytest.raises(ValueError, match='positive integer'):
        r.get_recent(supplier_code='demo_supplier',limit=0)


def test_no_latest_returns_none():
    _, f=make_factory(); assert repo(f).get_latest('demo_supplier') is None


def test_initial_changed_true():
    _, f=make_factory(); _,s=svc(f); assert s.record_snapshot(snap()).changed is True


def test_unchanged_changed_false():
    _, f=make_factory(); _,s=svc(f); s.record_snapshot(snap()); assert s.record_snapshot(snap()).changed is False


def test_run_ids_monotonic():
    _, f=make_factory(); _,s=svc(f); a=s.record_snapshot(snap()); b=s.record_snapshot(snap()); assert b.run.run_id>a.run.run_id


def test_same_state_flags_false():
    _, f=make_factory(); _,s=svc(f); s.record_snapshot(snap()); b=s.record_snapshot(snap())
    assert b.run.posture_changed==0 and b.run.next_action_changed==0


def test_links_to_previous_same_supplier_only():
    _, f=make_factory(); _,s=svc(f); a=s.record_snapshot(snap(supplier='a')); s.record_snapshot(snap(supplier='b')); a2=s.record_snapshot(snap(supplier='a',fingerprint='c'*64))
    assert a2.run.previous_run_id==a.run.run_id


def test_history_human_attention_to_idle():
    _, f=make_factory(); r,s=svc(f)
    s.record_snapshot(snap())
    s.record_snapshot(snap(posture=SupplierSystemPosture.IDLE, action=SupplierNextAction.NONE,
                           fingerprint='f'*64,awaiting=0,acknowledged=0,closed=3))
    latest=r.get_recent(supplier_code='demo_supplier',limit=1)[0]
    assert latest.posture=='idle' and latest.previous_posture=='human_attention'
