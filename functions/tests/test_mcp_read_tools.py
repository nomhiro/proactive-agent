import json
from datetime import datetime

import pytest
from vehicle_core.constants import JST, Team
from vehicle_core.hils_logs import render_hils_log
from vehicle_core.impact import analyze_impact
from vehicle_core.models import AgentMail, Message, Notification, TestRun
from vehicle_core.seed import build_dataset

from proactive_functions.handlers import load_graph
from proactive_functions.mcp.context import ToolContext
from proactive_functions.mcp.protocol import handle_rpc
from proactive_functions.mcp.server import build_registry
from tests.fakes import MemoryStore

NIGHT = datetime(2026, 11, 17, 21, 10, tzinfo=JST)
IC, MC, EV, CE = Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL, Team.EVALUATION, Team.CHIEF_ENGINEER
REGISTRY = build_registry()
LOG_PATH = "hils-logs/TC-HILS-031/s2-1.csv"


class FakeBlobs:
    def __init__(self, files: dict[str, str]):
        self.files = files

    def read_text(self, path: str) -> str | None:
        return self.files.get(path)


def notif(id_, team, created="2026-11-17T21:00:00+09:00"):
    return Notification(id=id_, team=team, origin_artifact_id=None, impacted_ids=[], highlight_ids=[],
                        cross_team_edges=[], classification="digest", deliver_at=None, reason="r",
                        created_at=created).model_dump(mode="json")


def mail(id_, frm, to):
    return AgentMail(id=id_, thread_id="t1", from_team=frm, to_team=to, kind="question", body="b",
                     created_at=NIGHT).model_dump(mode="json")


@pytest.fixture
def store():
    s = MemoryStore()
    ds = build_dataset()
    for a in ds.artifacts:
        s.create("artifacts", a.model_dump(mode="json"))
    for r in ds.test_runs:
        s.create("test_runs", r.model_dump(mode="json"))
    for ts in ds.team_settings:
        s.create("team_settings", ts.model_copy(update={"agent_client_id": f"cid-{ts.team.value}"})
                 .model_dump(mode="json"))
    s.create("test_runs", TestRun(id="run-s2-1", testcase_id="TC-HILS-031", feature="regen_coord", result="fail",
                                  executed_at=NIGHT, log_blob=LOG_PATH).model_dump(mode="json"))
    s.create("test_runs", TestRun(id="run-nolog", testcase_id="TC-HILS-031", feature="regen_coord", result="fail",
                                  executed_at=NIGHT).model_dump(mode="json"))
    for n in (notif("n-ic", IC), notif("n-mc", MC), notif("n-ev", EV)):
        s.create("notifications", n)
    for m in (mail("am-1", IC, MC), mail("am-2", MC, EV), mail("am-3", EV, IC)):
        s.create("agent_mail", m)
    for team in (IC, MC):
        s.create("messages", Message(id=f"msg-{team.value}", team=team, role="assistant", author="agent", text="t",
                                     created_at=NIGHT).model_dump(mode="json"))
    return s


def call_raw(store, name, args=None, team=IC, blobs=None):
    ctx = ToolContext(team=team, store=store, now=NIGHT, blobs=blobs)
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}
    return handle_rpc(msg, REGISTRY, ctx)["result"]


def call(store, name, args=None, team=IC, blobs=None):
    res = call_raw(store, name, args, team, blobs)
    assert res["isError"] is False, res["content"][0]["text"]
    return json.loads(res["content"][0]["text"])


def test_get_artifact_hides_store_fields(store):
    a = call(store, "get_artifact", {"artifact_id": "SIG-BrkPedalPos"})
    assert a["id"] == "SIG-BrkPedalPos" and not any(k.startswith("_") for k in a)


def test_unknown_artifact_is_is_error(store):
    assert call_raw(store, "get_artifact", {"artifact_id": "REQ-999"})["isError"] is True


def test_search_artifacts_by_type_and_text(store):
    out = call(store, "search_artifacts", {"type": "signal", "text": "BrkPedalPos"})
    assert [a["id"] for a in out] == ["SIG-BrkPedalPos"]


def test_search_artifacts_limit_is_capped(store):
    assert len(call(store, "search_artifacts", {"limit": 5})) == 5
    assert len(call(store, "search_artifacts", {"limit": 10_000})) <= 200


def test_trace_impact_matches_code(store):
    out = call(store, "trace_impact", {"artifact_id": "SIG-BrkPedalPos"})
    assert set(out["impacted_ids"]) == set(analyze_impact(load_graph(store), "SIG-BrkPedalPos").impacted_ids)


def test_get_test_runs_newest_first(store):
    runs = call(store, "get_test_runs", {"testcase_id": "TC-HILS-031"})
    assert runs[0]["executed_at"] >= runs[-1]["executed_at"]
    assert all(r["testcase_id"] == "TC-HILS-031" for r in runs)


def test_get_test_log_returns_csv(store):
    run = TestRun.model_validate(store.get("test_runs", "run-s2-1"))
    out = call(store, "get_test_log", {"test_run_id": "run-s2-1"}, blobs=FakeBlobs({LOG_PATH: render_hils_log(run)}))
    assert out["csv"].startswith("time_ms,") and out["truncated"] is False


def test_get_test_log_without_blob_is_is_error(store):
    res = call_raw(store, "get_test_log", {"test_run_id": "run-nolog"}, blobs=FakeBlobs({}))
    assert res["isError"] is True and "ログがありません" in res["content"][0]["text"]


def test_get_test_log_missing_blob_is_is_error(store):
    res = call_raw(store, "get_test_log", {"test_run_id": "run-s2-1"}, blobs=FakeBlobs({}))
    assert res["isError"] is True and "ログがありません" in res["content"][0]["text"]


def test_get_test_log_truncates_at_200000_chars(store):
    out = call(store, "get_test_log", {"test_run_id": "run-s2-1"}, blobs=FakeBlobs({LOG_PATH: "x" * 250_000}))
    assert len(out["csv"]) == 200_000 and out["truncated"] is True


def test_get_release_gaps(store):
    out = call(store, "get_release_gaps", {"release_id": "R3"})
    assert out["release_id"] == "R3" and isinstance(out["unverified_requirement_ids"], list)


def test_unknown_release_is_is_error(store):
    assert call_raw(store, "get_release_gaps", {"release_id": "R9"})["isError"] is True


def test_team_members_hide_agent_client_id(store):
    teams = call(store, "list_team_members")
    assert len(teams) == 7
    assert all("agent_client_id" not in t and "proactivity" not in t for t in teams)
    assert any(m["name_ja"] == "佐藤" for t in teams for m in t["members"])


def test_get_team_settings_is_own_team_without_client_id(store):
    out = call(store, "get_team_settings", team=MC)
    assert out["team"] == "motor_control" and "agent_client_id" not in out and "proactivity" in out


def test_non_chief_team_argument_is_replaced_by_caller(store):
    out = call(store, "list_notifications", {"team": "motor_control"}, team=IC)
    assert {n["team"] for n in out} == {"integrated_control"}


def test_chief_sees_all_teams_notifications(store):
    assert {n["team"] for n in call(store, "list_notifications", team=CE)} == {"integrated_control", "motor_control",
                                                                                "evaluation"}
    assert {n["team"] for n in call(store, "list_notifications", {"team": "evaluation"}, team=CE)} == {"evaluation"}


def test_list_mail_for_team_includes_sent_and_received_only(store):
    assert {m["id"] for m in call(store, "list_mail", team=IC)} == {"am-1", "am-3"}


def test_chief_sees_all_mail(store):
    assert {m["id"] for m in call(store, "list_mail", team=CE)} == {"am-1", "am-2", "am-3"}


def test_messages_are_own_team_even_for_chief(store):
    assert [m["id"] for m in call(store, "list_messages", team=IC)] == ["msg-integrated_control"]
    assert call(store, "list_messages", team=CE) == []


def test_list_notifications_since_compares_instants_not_strings(store):  # 最終レビューの M2
    # n-ic は 21:00 JST（12:00Z）。12:30Z より前なので含めない
    assert call(store, "list_notifications", {"since": "2026-11-17T12:30:00Z"}) == []
    assert [n["id"] for n in call(store, "list_notifications", {"since": "2026-11-17T11:30:00Z"})] == ["n-ic"]


class BrokenBlobs:
    def __init__(self, exc):
        self.exc = exc

    def read_text(self, path):
        raise self.exc


def test_get_test_log_with_malformed_blob_path_says_no_log(store):  # 最終レビューの M3
    res = call_raw(store, "get_test_log", {"test_run_id": "run-s2-1"}, blobs=BrokenBlobs(ValueError("bad path")))
    assert res["isError"] is True and "ログがありません" in res["content"][0]["text"]


def test_get_test_log_storage_error_says_cannot_read(store):  # 最終レビューの M3
    res = call_raw(store, "get_test_log", {"test_run_id": "run-s2-1"}, blobs=BrokenBlobs(RuntimeError("403")))
    assert res["isError"] is True and "ログを読めませんでした" in res["content"][0]["text"]
