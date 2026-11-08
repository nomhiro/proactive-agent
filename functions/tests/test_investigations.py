from datetime import datetime, timedelta

from vehicle_core.constants import JST
from vehicle_core.routing import InvestigationRequest

from proactive_functions.investigations import dispatch_due, enqueue
from tests.fakes import MemoryStore, RecordingInvoker


def req(id_, source, not_before, trigger="change", origin="SIG-BrkPedalPos", team="integrated_control"):
    return InvestigationRequest(id=id_, team=team, trigger=trigger, origin_artifact_id=origin,
                                source_ids=[source], impact=None, matched_watch_ids=[], floor="notify_now",
                                not_before=not_before)


T0 = datetime(2026, 11, 17, 21, 13, tzinfo=JST)


def test_enqueue_is_idempotent():
    store = MemoryStore()
    assert enqueue(store, [req("k1", "ce-1", T0)]) == ["k1"]
    assert enqueue(store, [req("k1", "ce-1", T0)]) == []
    assert len(store.query("investigations")) == 1
    assert store.get("investigations", "k1")["status"] == "pending"


def test_not_due_is_not_dispatched():
    store, inv = MemoryStore(), RecordingInvoker()
    enqueue(store, [req("k1", "ce-1", T0)])
    assert dispatch_due(store, inv, T0 - timedelta(seconds=1)) == []
    assert inv.calls == []


def test_due_single_request_dispatched_once():
    store, inv = MemoryStore(), RecordingInvoker()
    enqueue(store, [req("k1", "ce-1", T0)])
    assert dispatch_due(store, inv, T0) == ["k1"]
    assert dispatch_due(store, inv, T0 + timedelta(minutes=1)) == []
    assert [c.id for c in inv.calls] == ["k1"]
    rec = store.get("investigations", "k1")
    assert rec["status"] == "dispatched" and rec["dispatched_at"].startswith("2026-11-17T21:13")


def test_close_changes_are_merged_and_wait_for_the_last():
    store, inv = MemoryStore(), RecordingInvoker()
    enqueue(store, [req("k1", "ce-1", T0), req("k2", "ce-2", T0 + timedelta(seconds=60))])
    assert dispatch_due(store, inv, T0 + timedelta(seconds=30)) == []  # 2件目の窓がまだ
    [merged_id] = dispatch_due(store, inv, T0 + timedelta(seconds=60))
    assert inv.calls[0].source_ids == ["ce-1", "ce-2"]
    assert {store.get("investigations", k)["status"] for k in ("k1", "k2")} == {"merged"}
    assert {store.get("investigations", k)["merged_into"] for k in ("k1", "k2")} == {merged_id}
    assert store.get("investigations", merged_id)["status"] == "dispatched"


def test_other_triggers_are_not_merged():
    store, inv = MemoryStore(), RecordingInvoker()
    enqueue(store, [req("k1", "run-1", T0, trigger="test_run", origin="TC-HILS-031"),
                    req("k2", "run-2", T0, trigger="test_run", origin="TC-HILS-031")])
    assert sorted(dispatch_due(store, inv, T0)) == ["k1", "k2"]


def test_concurrent_tick_loses_claim_and_skips():
    # Review Focus 4: 確保の直前に別の tick が同じ記録を書き換えた
    store, inv = MemoryStore(), RecordingInvoker()
    enqueue(store, [req("k1", "ce-1", T0)])
    store.before_replace = lambda c, d: store.touch(c, d["id"])  # 置き換えの直前に etag を変える
    assert dispatch_due(store, inv, T0) == []
    assert inv.calls == []


def test_invoker_failure_is_recorded():
    store = MemoryStore()
    enqueue(store, [req("k1", "ce-1", T0)])
    assert dispatch_due(store, RecordingInvoker(fail=True), T0) == []
    rec = store.get("investigations", "k1")
    assert rec["status"] == "failed" and rec["error"]



def test_merged_group_already_claimed_by_other_tick_is_skipped():  # 最終レビューの指摘3
    from vehicle_core.routing import coalesce
    store, inv = MemoryStore(), RecordingInvoker()
    reqs = [req("k1", "ce-1", T0), req("k2", "ce-2", T0 + timedelta(seconds=60))]
    enqueue(store, reqs)
    [merged] = coalesce(reqs)
    store.create("investigations", {"id": merged.id, "vehicle_id": "kakuu-suv", "status": "dispatched"})
    assert dispatch_due(store, inv, T0 + timedelta(seconds=60)) == []
    assert inv.calls == []
    assert {store.get("investigations", k)["status"] for k in ("k1", "k2")} == {"merged"}
