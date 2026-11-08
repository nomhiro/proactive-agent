from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import ANY

import pytest
from pydantic import ValidationError
from vehicle_core.constants import AGENT_TEAMS, JST, VEHICLE_ID, Team

from proactive_functions.foundry_invoker import (
    FoundryInvoker,
    FoundryResponsesClient,
    FoundryRoutineDispatcher,
    morning_dispatch_due,
    reconcile_runs,
)
from proactive_functions.investigations import dispatch_due, enqueue
from proactive_functions.settings import load_settings
from proactive_functions.tick import run_tick
from tests.fakes import MemoryStore, RecordingPublisher
from tests.test_prompts import req_s1

NOW = datetime(2026, 11, 17, 21, 20, tzinfo=JST)


class FakeResponses:
    def __init__(self, statuses=None, fail=False):
        self.calls = []
        self.statuses = statuses or {}
        self.fail = fail

    def create_conversation(self) -> str:
        self.calls.append(("create_conversation",))
        if self.fail:
            raise RuntimeError("foundry unavailable")
        return "conv-1"

    def start_response(self, conversation_id: str, prompt: str) -> str:
        self.calls.append(("start_response", conversation_id, prompt))
        return "resp-1"

    def response_status(self, response_id: str) -> str:
        self.calls.append(("response_status", response_id))
        return self.statuses[response_id]


def clock():
    return NOW


def test_invoke_creates_conversation_starts_background_response_and_records_ids():
    store, fake = MemoryStore(), FakeResponses()
    enqueue(store, [req_s1])
    FoundryInvoker(store, lambda t: fake, clock).invoke(req_s1)
    assert fake.calls == [("create_conversation",), ("start_response", "conv-1", ANY)]
    rec = store.get("investigations", req_s1.id)
    assert rec["conversation_id"] == "conv-1" and rec["response_id"] == "resp-1"
    run = store.get("agent_runs", f"run-inv-{req_s1.id}")
    assert run["state"] == "running" and run["detail"]["response_id"] == "resp-1"
    assert run["team"] == req_s1.team.value
    assert f"run-inv-{req_s1.id}" in fake.calls[1][2]


def test_invoke_uses_team_agent():
    store, fake, asked = MemoryStore(), FakeResponses(), []
    enqueue(store, [req_s1])

    def client_for(team):
        asked.append(team)
        return fake
    FoundryInvoker(store, client_for, clock).invoke(req_s1)
    assert asked == [Team.MOTOR_CONTROL]


def test_invoke_failure_propagates_so_dispatch_marks_failed():
    store = MemoryStore()
    enqueue(store, [req_s1.model_copy(update={"not_before": NOW - timedelta(minutes=5)})])
    invoker = FoundryInvoker(store, lambda t: FakeResponses(fail=True), clock)
    assert dispatch_due(store, invoker, NOW) == []
    assert store.get("investigations", req_s1.id)["status"] == "failed"
    assert store.get("agent_runs", f"run-inv-{req_s1.id}") is None


def test_foundry_client_sends_no_harness_managed_params():
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(id="resp-9")
    openai = SimpleNamespace(
        conversations=SimpleNamespace(create=lambda: SimpleNamespace(id="conv-9")),
        responses=SimpleNamespace(create=create, retrieve=lambda rid: SimpleNamespace(status="completed")))
    client = FoundryResponsesClient("https://p", None, "asst-motor-control", openai_client=openai)
    assert client.create_conversation() == "conv-9"
    assert client.start_response("conv-9", "hi") == "resp-9"
    assert set(sent) == {"conversation", "input", "background"} and sent["background"] is True
    assert client.response_status("resp-9") == "completed"


# --- 終わらなかった調査の片付け（決定 11） ------------------------------------

def running(store, run_id, started, response_id="resp-1", team="motor_control"):
    store.create("agent_runs", {"id": run_id, "vehicle_id": VEHICLE_ID, "team": team, "state": "running", "title": "t",
                                "started_at": started.isoformat(), "detail": {"response_id": response_id}})


def test_reconcile_closes_failed_response():
    store = MemoryStore()
    running(store, "run-a", NOW - timedelta(minutes=5))
    fake = FakeResponses({"resp-1": "failed"})
    assert reconcile_runs(store, lambda t: fake, NOW) == ["run-a"]
    run = store.get("agent_runs", "run-a")
    assert run["state"] == "done" and run["detail"]["error"] == "failed" and run["finished_at"]


def test_reconcile_closes_completed_but_running():
    store = MemoryStore()
    running(store, "run-a", NOW - timedelta(minutes=5))
    assert reconcile_runs(store, lambda t: FakeResponses({"resp-1": "completed"}), NOW) == ["run-a"]
    run = store.get("agent_runs", "run-a")
    assert run["state"] == "done" and run["detail"]["closed_by"] == "tick" and "error" not in run["detail"]


def test_reconcile_leaves_in_progress_and_recent_runs():
    store = MemoryStore()
    running(store, "run-recent", NOW - timedelta(seconds=90), response_id="resp-r")
    running(store, "run-busy", NOW - timedelta(minutes=10), response_id="resp-b")
    running(store, "run-queued", NOW - timedelta(minutes=10), response_id="resp-q")
    store.create("agent_runs", {"id": "run-noresp", "vehicle_id": VEHICLE_ID, "team": "motor_control", "state": "running", "title": "t",
                                "started_at": (NOW - timedelta(hours=1)).isoformat(), "detail": {}})
    fake = FakeResponses({"resp-r": "failed", "resp-b": "in_progress", "resp-q": "queued"})
    assert reconcile_runs(store, lambda t: fake, NOW) == []
    assert ("response_status", "resp-r") not in fake.calls
    assert all(store.get("agent_runs", i)["state"] == "running"
               for i in ["run-recent", "run-busy", "run-queued", "run-noresp"])


def test_reconcile_survives_status_lookup_error():
    store = MemoryStore()
    running(store, "run-a", NOW - timedelta(minutes=5), response_id="resp-missing")
    running(store, "run-b", NOW - timedelta(minutes=5), response_id="resp-1")
    fake = FakeResponses({"resp-1": "cancelled"})  # resp-missing は KeyError
    assert reconcile_runs(store, lambda t: fake, NOW) == ["run-b"]


# --- 設定 ------------------------------------------------------------------

BASE_ENV = {"COSMOS_ENDPOINT": "https://c", "WEBPUBSUB_ENDPOINT": "https://w", "GATEWAY_TENANT_ID": "t",
            "GATEWAY_AUDIENCES": "api://x"}


def test_settings_require_endpoint_for_foundry_invoker():
    with pytest.raises(ValidationError):
        load_settings(BASE_ENV | {"AGENT_INVOKER": "foundry"})
    s = load_settings(BASE_ENV | {"AGENT_INVOKER": "foundry", "FOUNDRY_PROJECT_ENDPOINT": "https://p"})
    assert s.agent_invoker == "foundry" and s.foundry_project_endpoint == "https://p"


# --- 時計を進めたときの Routines の手動起動（決定 17） --------------------------

A = 1000.0  # 前回のずれ（秒）
B = A + (datetime(2026, 11, 18, 8, 0, tzinfo=JST) - datetime(2026, 11, 17, 21, 14, tzinfo=JST)).total_seconds()


def test_morning_dispatch_when_clock_moved_across_8am():
    store = MemoryStore()
    assert morning_dispatch_due(store, datetime(2026, 11, 17, 21, 14, tzinfo=JST), A) is False
    assert morning_dispatch_due(store, datetime(2026, 11, 18, 8, 0, tzinfo=JST), B) is True
    # 同じずれのままの次の tick では起動しない
    assert morning_dispatch_due(store, datetime(2026, 11, 18, 8, 1, tzinfo=JST), B) is False


def test_no_dispatch_when_real_time_passes_8am():
    store = MemoryStore()
    morning_dispatch_due(store, datetime(2026, 11, 18, 7, 59, tzinfo=JST), A)
    assert morning_dispatch_due(store, datetime(2026, 11, 18, 8, 1, tzinfo=JST), A) is False


def test_no_dispatch_when_clock_moved_within_day():
    store = MemoryStore()
    morning_dispatch_due(store, datetime(2026, 11, 18, 9, 0, tzinfo=JST), A)
    assert morning_dispatch_due(store, datetime(2026, 11, 18, 15, 0, tzinfo=JST), A + 6 * 3600) is False


def test_first_tick_without_last_tick_does_not_dispatch():
    store = MemoryStore()
    assert morning_dispatch_due(store, datetime(2026, 11, 18, 8, 0, tzinfo=JST), B) is False
    assert store.get("system", "last_tick")["offset_seconds"] == B


def test_last_tick_is_not_rewritten_when_offset_is_unchanged():
    # system コンテナーへの書き込みは tick をもう一度起こすので、ずれが同じなら書かない（tick が止まらなくなる）
    store = MemoryStore()
    morning_dispatch_due(store, datetime(2026, 11, 18, 9, 0, tzinfo=JST), A)
    etag = store.get("system", "last_tick")["_etag"]
    morning_dispatch_due(store, datetime(2026, 11, 18, 9, 5, tzinfo=JST), A)
    assert store.get("system", "last_tick")["_etag"] == etag


class RecordingDispatcher:
    def __init__(self, fail_team=None):
        self.teams = []
        self.fail_team = fail_team

    def dispatch(self, team):
        self.teams.append(team)
        if team == self.fail_team:
            raise RuntimeError("routine dispatch failed")


def test_tick_dispatches_all_four_and_survives_one_failure():
    store, routines = MemoryStore(), RecordingDispatcher(fail_team=Team.INTEGRATED_CONTROL)
    inv = FoundryInvoker(store, lambda t: FakeResponses(), clock)
    run_tick(store, inv, RecordingPublisher(), datetime(2026, 11, 17, 21, 14, tzinfo=JST),
             routines=routines, offset_seconds=A)
    assert routines.teams == []
    report = run_tick(store, inv, RecordingPublisher(), datetime(2026, 11, 18, 8, 0, tzinfo=JST),
                      routines=routines, offset_seconds=B)
    assert set(routines.teams) == set(AGENT_TEAMS)
    assert set(report.routine_teams) == {t.value for t in AGENT_TEAMS} - {"integrated_control"}


def test_tick_reconciles_only_with_foundry_invoker():
    store = MemoryStore()
    running(store, "run-a", NOW - timedelta(minutes=5))
    report = run_tick(store, FoundryInvoker(store, lambda t: FakeResponses({"resp-1": "failed"}), clock),
                      RecordingPublisher(), NOW)
    assert report.reconciled_run_ids == ["run-a"]


def test_routine_dispatcher_uses_morning_routine_name():
    calls = []
    project = SimpleNamespace(beta=SimpleNamespace(routines=SimpleNamespace(
        dispatch=lambda **kw: calls.append(kw))))
    FoundryRoutineDispatcher("https://p", None, project=project).dispatch(Team.CHIEF_ENGINEER)
    assert calls == [{"routine_name": "morning-asst-chief-engineer"}]
