from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from proactive_functions.clock import StoredClock
from vehicle_core.constants import JST, VEHICLE_ID
from vehicle_core.scenarios import SCENARIOS

from proactive_web.app import Deps, create_app
from proactive_web.chat import ChatService
from proactive_web.scenario_runner import (
    PEOPLE,
    ScenarioRunner,
    StepNotReady,
    step_summary,
)
from tests.helpers import NIGHT, REAL, run
from tests.test_chat import FakeChatClient

USER = {"X-MS-CLIENT-PRINCIPAL-NAME": "someone@example.com"}


class FixedSystem:
    def now(self):
        return REAL


def vnow(store) -> datetime:
    return StoredClock(store, FixedSystem()).now()


@pytest.fixture
def chat_client():
    return FakeChatClient()


@pytest.fixture
def runner(store, chat_client):
    chat = ChatService(store, chat_client, lambda: vnow(store))
    return ScenarioRunner(store, chat, system_now=lambda: REAL)


def settle(store) -> None:
    """Functions の代わりに、変更イベント・試験結果・メールから調査依頼を作り、どれも終わったことにする。"""
    from proactive_functions.handlers import handle_agent_mail, handle_change_events, handle_test_runs
    handle_change_events(store.query("change_events"), store)
    handle_test_runs(store.query("test_runs"), store)
    handle_agent_mail(store.query("agent_mail"), store)
    for inv in store.query("investigations"):
        if inv.get("status") == "pending":
            store.upsert("investigations", inv | {"status": "dispatched"})
        if store.get("agent_runs", f"run-inv-{inv['id']}") is None:
            store.create("agent_runs", run(f"run-inv-{inv['id']}", team=inv.get("team", "integrated_control"),
                                           state="done", detail={"investigation_id": inv["id"]}))


def add_pending_notice(store, id_="prop-1", created_at=NIGHT):
    store.create("proposals", {
        "id": id_, "vehicle_id": VEHICLE_ID, "team": "integrated_control", "kind": "impact_notice",
        "to_teams": ["motor_control"], "draft": "下書き", "related_artifact_ids": [], "thread_id": f"th-{id_}",
        "status": "pending", "decided_by": None, "decided_at": None, "created_at": created_at.isoformat()})


def test_first_step_moves_clock_to_change_time_and_writes_event_and_artifact(store, runner):
    done = runner.next()
    assert done["index"] == 0 and done["kind"] == "change" and done["done"] is True
    assert vnow(store) == datetime(2026, 11, 17, 21, 10, tzinfo=JST)
    event = store.get("change_events", "ce-s1-1")
    assert event is not None and "origin" not in event
    art = store.get("artifacts", "SIG-BrkPedalPos")
    assert art["attributes"]["period_ms"] == 20
    assert art["updated_at"] == datetime(2026, 11, 17, 21, 10, tzinfo=JST).isoformat()
    assert [s["done"] for s in runner.steps()][:2] == [True, False]


def test_clock_is_never_moved_backwards(store, runner):
    from proactive_functions.clock import set_virtual_now
    later = datetime(2026, 11, 17, 23, 0, tzinfo=JST)
    set_virtual_now(store, later, REAL)
    runner.next()
    assert vnow(store) == later
    assert store.get("change_events", "ce-s1-1") is not None


def test_approve_step_without_pending_proposal_is_not_ready_and_changes_nothing(store, runner):  # Review Focus 5
    runner.next()  # 変更
    settle(store)
    runner.next()  # 8:00
    clock_before = store.get("system", "clock")["offset_seconds"]
    with pytest.raises(StepNotReady, match="承認待ち"):
        runner.next()
    assert store.get("system", "clock")["offset_seconds"] == clock_before
    assert runner.steps()[2]["done"] is False


def test_clock_step_waits_for_running_investigation(store, runner):  # Review Focus 6
    runner.next()  # 21:10 の変更
    settle(store)
    store.create("agent_runs", run("run-inv-x", state="running", detail={"investigation_id": "x"}))
    with pytest.raises(StepNotReady, match="調査が終わっていません"):
        runner.next()
    assert vnow(store) == datetime(2026, 11, 17, 21, 10, tzinfo=JST)
    store.upsert("agent_runs", store.get("agent_runs", "run-inv-x") | {"state": "done"})
    runner.next()  # 終われば進める
    assert vnow(store) == datetime(2026, 11, 18, 8, 0, tzinfo=JST)


def test_clock_step_waits_for_pending_investigation_but_not_for_chat_runs(store, runner):
    runner.next()
    settle(store)
    store.create("agent_runs", run("run-chat-m1", state="running", detail={"kind": "chat"}))
    store.create("investigations", {"id": "inv-1", "vehicle_id": VEHICLE_ID, "status": "pending"})
    with pytest.raises(StepNotReady, match="inv-1"):
        runner.next()
    store.upsert("investigations", store.get("investigations", "inv-1") | {"status": "dispatched"})
    store.create("agent_runs", run("run-inv-inv-1", state="done", detail={"investigation_id": "inv-1"}))
    runner.next()


def test_clock_step_waits_until_change_is_routed(store, runner):  # 最終レビュー Important 4(a)
    runner.next()  # 21:10 の変更。変更フィードのトリガーはまだ調査依頼を作っていない
    with pytest.raises(StepNotReady, match="調査が終わっていません"):
        runner.next()
    assert vnow(store) == datetime(2026, 11, 17, 21, 10, tzinfo=JST)
    settle(store)
    runner.next()
    assert vnow(store) == datetime(2026, 11, 18, 8, 0, tzinfo=JST)


def test_clock_step_waits_for_dispatched_investigation_until_its_run_finishes(store, runner):  # Important 4(b)
    from proactive_functions.handlers import handle_change_events
    runner.next()
    handle_change_events(store.query("change_events"), store)
    inv = store.query("investigations")[0]
    store.upsert("investigations", inv | {"status": "dispatched"})  # 起動の直前（作業記録はまだない）
    with pytest.raises(StepNotReady, match="調査が終わっていません"):
        runner.next()
    store.create("agent_runs", run(f"run-inv-{inv['id']}", state="running", detail={"investigation_id": inv["id"]}))
    with pytest.raises(StepNotReady):
        runner.next()
    store.upsert("agent_runs", store.get("agent_runs", f"run-inv-{inv['id']}") | {"state": "done"})
    runner.next()


def test_clock_step_follows_merged_investigation(store, runner):
    from proactive_functions.handlers import handle_change_events
    runner.next()
    handle_change_events(store.query("change_events"), store)
    inv = store.query("investigations")[0]
    store.upsert("investigations", inv | {"status": "merged", "merged_into": "inv-merged"})
    store.create("investigations", {"id": "inv-merged", "vehicle_id": VEHICLE_ID, "status": "dispatched"})
    with pytest.raises(StepNotReady, match="調査が終わっていません"):
        runner.next()
    store.create("agent_runs", run("run-inv-inv-merged", state="done", detail={"investigation_id": "inv-merged"}))
    runner.next()


def test_clock_step_waits_for_mail_not_yet_routed(store, runner):  # Important 4（メールから起きる調査）
    runner.next()
    settle(store)
    store.create("agent_mail", {"id": "am-x", "vehicle_id": VEHICLE_ID, "thread_id": "th-x",
                                "from_team": "integrated_control", "to_team": "evaluation",
                                "kind": "analysis_request", "body": "解析して", "related_artifact_ids": [],
                                "created_at": NIGHT.isoformat()})
    with pytest.raises(StepNotReady, match="調査が終わっていません"):
        runner.next()
    settle(store)
    runner.next()


def test_approve_step_completes_when_presenter_already_approved_in_ui(store, runner):  # Important 3
    from proactive_web.personas import PERSONAS
    from proactive_web.proposals import decide_proposal
    runner.next()
    settle(store)
    runner.next()
    add_pending_notice(store)
    decide_proposal(store, "prop-1", PERSONAS["tanaka"], "approve", "画面で直した本文", vnow(store))
    store.delete("agent_mail", "am-prop-1-motor_control")  # メールを書く途中で止まっていた
    done = runner.next()
    assert done["index"] == 2 and done["done"] is True
    assert vnow(store) == datetime(2026, 11, 18, 8, 20, tzinfo=JST)
    assert store.get("agent_mail", "am-prop-1-motor_control")["body"] == "画面で直した本文"


def test_admin_next_collects_chat_replies_first(store, chat_client):  # Important 6
    from proactive_web.personas import PERSONAS
    chat = ChatService(store, chat_client, lambda: vnow(store))
    deps = Deps(store=store, clock=StoredClock(store, FixedSystem()), chat=chat, system_now=lambda: REAL)
    c = TestClient(create_app(deps))
    mid = chat.send(PERSONAS["tanaka"], "田中の質問")  # 画面は高橋に切り替えていて、田中の返事は誰も受け取っていない
    chat_client.finish("completed", "答え")
    c.post("/api/admin/next", headers=USER)
    assert store.get("agent_runs", f"run-chat-{mid}")["state"] == "done"


def test_approve_step_approves_oldest_pending_impact_notice_as_tanaka(store, runner):
    runner.next()
    settle(store)
    runner.next()
    add_pending_notice(store, "prop-new", created_at=datetime(2026, 11, 17, 22, 0, tzinfo=JST))
    add_pending_notice(store, "prop-old", created_at=datetime(2026, 11, 17, 21, 20, tzinfo=JST))
    runner.next()
    old = store.get("proposals", "prop-old")
    assert old["status"] == "approved" and old["decided_by"] == "tanaka"
    assert old["decided_at"] == datetime(2026, 11, 18, 8, 20, tzinfo=JST).isoformat()
    assert store.get("proposals", "prop-new")["status"] == "pending"
    assert store.get("agent_mail", "am-prop-old-motor_control") is not None


def test_human_says_step_sends_chat_as_person(store, runner, chat_client):
    runner.next(); settle(store); runner.next(); add_pending_notice(store); runner.next()
    runner.next()
    team, _, prompt = chat_client.prompts[-1]
    assert team.value == "motor_control"
    assert prompt.endswith("佐藤（モーター制御、モータートルク制御の主担当）: 今週は v2.1 で手一杯で、R3 までに 20ms 対応は無理です")
    assert vnow(store) == datetime(2026, 11, 18, 8, 40, tzinfo=JST)


def test_human_says_step_is_not_ready_while_chat_busy(store, runner):
    runner.next(); settle(store); runner.next(); add_pending_notice(store); runner.next()
    store.create("agent_runs", run("run-chat-x", team="motor_control", detail={"kind": "chat"}))
    with pytest.raises(StepNotReady, match="返事"):
        runner.next()
    assert runner.steps()[3]["done"] is False


def test_reset_clears_progress_and_restores_seed_clock(store, runner):
    runner.next()
    runner.reset()
    assert all(not s["done"] for s in runner.steps())
    assert vnow(store) == datetime(2026, 11, 17, 18, 0, tzinfo=JST)
    assert store.get("change_events", "ce-s1-1") is None


def test_all_steps_listed_in_order(runner):
    steps = runner.steps()
    assert steps[0]["scenario_id"] == "s1_signal_period" and steps[0]["scenario_title"] == "CAN 信号の周期変更"
    assert steps[-1]["scenario_id"] == "s4_release_gap"
    assert [s["index"] for s in steps] == list(range(len(steps)))


def test_finished_scenarios_are_not_ready(store, runner):
    store.upsert("system", {"id": "scenario_progress", "vehicle_id": VEHICLE_ID, "next_index": len(runner.steps())})
    with pytest.raises(StepNotReady, match="すべて終わりました"):
        runner.next()


def test_step_summary_is_japanese():
    s1 = SCENARIOS["s1_signal_period"].steps
    assert step_summary(s1[0], PEOPLE) == "11/17 21:10 田中が SIG-BrkPedalPos の attributes.period_ms を 10 から 20 に変える"
    assert step_summary(s1[1], PEOPLE) == "11/18 08:00 まで時計を進める"
    assert step_summary(s1[2], PEOPLE) == "11/18 08:20 田中が承認待ちの影響の連絡を送る"
    assert step_summary(s1[3], PEOPLE) == "11/18 08:40 佐藤: 今週は v2.1 で手一杯で、R3 までに 20ms 対応は無理です"
    s2 = SCENARIOS["s2_hils_streak"].steps
    assert step_summary(s2[0], PEOPLE) == "11/18 10:00 TC-HILS-031 の試験結果（fail）が入る"
    s0 = SCENARIOS["s0_noise"].steps
    assert step_summary(s0[0], PEOPLE) == "11/18 17:30 田中が SPEC-BRK-04 の description を直す"


def test_admin_routes(store, chat_client):
    chat = ChatService(store, chat_client, lambda: vnow(store))
    deps = Deps(store=store, clock=StoredClock(store, FixedSystem()), chat=chat, system_now=lambda: REAL)
    c = TestClient(create_app(deps))
    body = c.get("/api/admin/steps", headers=USER).json()
    assert body["steps"][0]["done"] is False and body["now"].startswith("2026-11-17T18:00")
    assert c.post("/api/admin/next", headers=USER).json()["index"] == 0
    settle(store)
    c.post("/api/admin/next", headers=USER)
    r = c.post("/api/admin/next", headers=USER)
    assert r.status_code == 409 and "承認待ち" in r.json()["detail"]
    r = c.post("/api/admin/clock", json={"at": "2026-11-18T09:00:00+09:00"}, headers=USER)
    assert r.status_code == 200 and vnow(store) == datetime(2026, 11, 18, 9, 0, tzinfo=JST)
    assert c.post("/api/admin/clock", json={"at": "あした"}, headers=USER).status_code == 422
    assert c.post("/api/admin/clock", json={"at": "2026-11-18T09:00:00"}, headers=USER).status_code == 422
    assert c.post("/api/admin/reset", headers=USER).status_code == 200
    assert c.get("/api/admin/steps", headers=USER).json()["steps"][0]["done"] is False
    assert c.post("/api/admin/next").status_code == 401
