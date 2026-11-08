from datetime import datetime, timedelta

from vehicle_core.constants import JST
from vehicle_core.models import AgentMail, Notification
from vehicle_core.seed import build_dataset, build_schedules

from proactive_functions.tick import TickReport, run_tick
from tests.fakes import MemoryStore, RecordingInvoker, RecordingPublisher

NIGHT = datetime(2026, 11, 17, 21, 10, tzinfo=JST)
MORNING = datetime(2026, 11, 18, 8, 0, tzinfo=JST)


def notif(id_, deliver_at, delivered_at=None):
    return Notification(id=id_, team="integrated_control", origin_artifact_id="SIG-BrkPedalPos", impacted_ids=[],
                        highlight_ids=[], cross_team_edges=[], classification="notify_now", deliver_at=deliver_at,
                        delivered_at=delivered_at, reason="r", created_at=NIGHT).model_dump(mode="json")


def tick(store, now, pub=None, inv=None):
    return run_tick(store, inv or RecordingInvoker(), pub or RecordingPublisher(), now)


def seeded_schedules():
    store = MemoryStore()
    for s in build_schedules(build_dataset()):
        store.create("schedules", s.model_dump(mode="json"))
    return store


def test_deferred_notification_delivered_once_at_morning():
    store, pub = MemoryStore(), RecordingPublisher()
    store.create("notifications", notif("n1", MORNING))
    assert tick(store, NIGHT, pub).delivered_notification_ids == []
    assert tick(store, MORNING, pub).delivered_notification_ids == ["n1"]
    assert tick(store, MORNING + timedelta(minutes=1), pub).delivered_notification_ids == []
    assert pub.events == [("integrated_control",
                           {"type": "refresh", "kind": "notifications", "id": "n1", "team": "integrated_control"})]
    assert store.get("notifications", "n1")["delivered_at"].startswith("2026-11-18T08:00")


def test_notification_without_deliver_at_is_never_delivered():
    store = MemoryStore()
    store.create("notifications", notif("n1", None))
    assert tick(store, MORNING).delivered_notification_ids == []


def test_daily_schedule_runs_and_creates_next():
    store = seeded_schedules()
    inv = RecordingInvoker()
    rep = tick(store, MORNING, inv=inv)
    assert "sch-digest-integrated_control-20261118" in rep.ran_schedule_ids
    assert store.get("schedules", "sch-digest-integrated_control-20261118")["done_at"] is not None
    assert store.get("schedules", "sch-digest-integrated_control-20261119")["due_at"].startswith("2026-11-19T08:00")
    assert "sch-release-gap-R3" not in rep.ran_schedule_ids
    assert {c.team for c in inv.calls if c.trigger == "schedule"} == {
        "integrated_control", "motor_control", "evaluation", "chief_engineer"}


def test_jump_several_days_runs_daily_once_and_next_is_future():  # Review Focus 3
    store = seeded_schedules()
    jump = datetime(2026, 11, 23, 8, 0, tzinfo=JST)
    rep = tick(store, jump)
    digests = [i for i in rep.ran_schedule_ids if i.startswith("sch-digest-integrated_control")]
    assert digests == ["sch-digest-integrated_control-20261118"]
    assert "sch-release-gap-R3" in rep.ran_schedule_ids
    pending = [s["id"] for s in store.query("schedules", {"done_at": None})
               if s["id"].startswith("sch-digest-integrated_control")]
    assert pending == ["sch-digest-integrated_control-20261124"]


def test_overdue_reply_wakes_sender_once():
    store = MemoryStore()
    sent = datetime(2026, 11, 18, 8, 10, tzinfo=JST)
    store.create("agent_mail", AgentMail(id="am-1", thread_id="th-1", from_team="integrated_control",
                                         to_team="motor_control", kind="impact_notice", body="x",
                                         created_at=sent).model_dump(mode="json"))
    assert tick(store, sent + timedelta(hours=47)).overdue_thread_ids == []
    rep = tick(store, sent + timedelta(hours=48))
    assert rep.overdue_thread_ids == ["th-1"]
    recs = store.query("investigations", {"trigger": "mail"})
    assert [r["team"] for r in recs] == ["integrated_control"]
    assert recs[0]["source_ids"] == ["overdue:th-1"]
    tick(store, sent + timedelta(hours=49))
    assert len(store.query("investigations", {"trigger": "mail"})) == 1


def test_tick_with_earlier_clock_changes_nothing():
    store = MemoryStore()
    store.create("notifications", notif("n1", MORNING, delivered_at=MORNING))
    rep = tick(store, NIGHT)
    assert rep == TickReport(delivered_notification_ids=[], ran_schedule_ids=[], overdue_thread_ids=[],
                             dispatched_ids=[])
    assert store.get("notifications", "n1")["delivered_at"] is not None



# --- 最終レビューの指摘2: 壊れた文書が1件あっても tick は止まらない ---

def test_malformed_notification_does_not_stop_tick():
    store = seeded_schedules()
    store.create("notifications", {"id": "n-bad", "vehicle_id": "kakuu-suv", "classification": "nonsense"})
    store.create("schedules", {"id": "s-bad", "vehicle_id": "kakuu-suv", "due_at": "not a date"})
    store.create("agent_mail", {"id": "am-bad", "vehicle_id": "kakuu-suv", "kind": "impact_notice"})
    rep = tick(store, MORNING)
    assert "sch-digest-integrated_control-20261118" in rep.ran_schedule_ids


# --- 最終レビューの指摘4: 実行済みの印を付ける前に、次の回と依頼を作る ---

def test_follow_up_exists_even_if_marking_done_fails():
    import pytest
    store = seeded_schedules()

    def fail_on_schedules(container, doc):
        if container == "schedules":
            raise RuntimeError("インスタンスが止まった")
    store.before_replace = fail_on_schedules
    with pytest.raises(RuntimeError):
        tick(store, MORNING)
    assert store.get("schedules", "sch-digest-integrated_control-20261119") is not None or         store.get("schedules", "sch-digest-motor_control-20261119") is not None or         store.get("schedules", "sch-briefing-chief_engineer-20261119") is not None or         store.get("schedules", "sch-digest-evaluation-20261119") is not None
    assert store.query("investigations", {"trigger": "schedule"}) != []
