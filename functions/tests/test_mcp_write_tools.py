import json
from datetime import datetime, timedelta

import pytest
from vehicle_core.constants import JST, Team
from vehicle_core.impact import analyze_impact
from vehicle_core.seed import build_dataset

from proactive_functions.handlers import load_graph
from proactive_functions.mcp.context import ToolContext
from proactive_functions.mcp.protocol import handle_rpc
from proactive_functions.mcp.server import build_registry
from tests.fakes import MemoryStore

NIGHT = datetime(2026, 11, 17, 21, 10, tzinfo=JST)
DAY = datetime(2026, 11, 18, 10, 0, tzinfo=JST)
IC, MC = Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL
SIGNAL_ID = "SIG-BrkPedalPos"
REGISTRY = build_registry()


@pytest.fixture
def store():
    s = MemoryStore()
    ds = build_dataset()
    for a in ds.artifacts:
        s.create("artifacts", a.model_dump(mode="json"))
    for ts in ds.team_settings:
        s.create("team_settings", ts.model_dump(mode="json"))
    return s


def call_raw(store, name, args, team=IC, now=NIGHT) -> dict:
    ctx = ToolContext(team=team, store=store, now=now)
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
    return handle_rpc(msg, REGISTRY, ctx)["result"]


def call(store, name, args, team=IC, now=NIGHT):
    res = call_raw(store, name, args, team, now)
    assert res["isError"] is False, res["content"][0]["text"]
    return json.loads(res["content"][0]["text"])


def test_post_message_ignores_caller_supplied_team_and_author(store):
    out = call(store, "post_message", {"text": "確認しました", "team": "motor_control", "author": "tanaka",
                                       "id": "msg-x", "role": "human"})
    saved = store.get("messages", out["id"])
    assert saved["team"] == "integrated_control" and saved["author"] == "agent" and saved["role"] == "assistant"
    assert out["id"] != "msg-x" and out["id"].startswith("msg-")


def test_post_message_keeps_attachments(store):
    out = call(store, "post_message", {"text": "グラフ", "attachments": ["foundry-file:assistant-abc"]})
    assert store.get("messages", out["id"])["attachments"] == ["foundry-file:assistant-abc"]


def test_send_mail_rejects_impact_notice(store):
    res = call_raw(store, "send_mail", {"to_team": "motor_control", "kind": "impact_notice", "body": "影響あり"})
    assert res["isError"] is True


def test_send_mail_analysis_request_creates_thread(store):
    out = call(store, "send_mail", {"to_team": "evaluation", "kind": "analysis_request", "body": "周期変更の影響を解析して",
                                    "related_artifact_ids": [SIGNAL_ID]})
    mail = store.get("agent_mail", out["id"])
    assert mail["from_team"] == "integrated_control" and mail["thread_id"] == out["thread_id"]


def test_create_proposal_for_impact_notice_is_pending(store):
    out = call(store, "create_proposal", {"kind": "impact_notice", "to_teams": ["motor_control", "evaluation"],
                                          "draft": "SIG-BrkPedalPos の周期変更が MDL-MotorTq に影響します",
                                          "related_artifact_ids": [SIGNAL_ID]})
    p = store.get("proposals", out["id"])
    assert p["status"] == "pending" and p["team"] == "integrated_control" and p["thread_id"] == out["thread_id"]


def test_create_proposal_cannot_be_pre_approved(store):
    out = call(store, "create_proposal", {"kind": "impact_notice", "to_teams": ["motor_control"], "draft": "d",
                                          "status": "approved", "decided_by": "tanaka"})
    p = store.get("proposals", out["id"])
    assert p["status"] == "pending" and p["decided_by"] is None


def test_record_notification_derives_evidence_from_origin(store):
    out = call(store, "record_notification", {"classification": "notify_now", "reason": "R3 に響く",
                                              "origin_artifact_id": SIGNAL_ID, "impacted_ids": ["REQ-999"]})
    n = store.get("notifications", out["id"])
    expected = analyze_impact(load_graph(store), SIGNAL_ID)
    assert set(n["impacted_ids"]) == set(expected.impacted_ids)
    assert set(n["highlight_ids"]) == set(expected.highlight_ids)
    assert "REQ-999" not in n["impacted_ids"]


def test_record_notification_unknown_origin_is_is_error(store):
    res = call_raw(store, "record_notification", {"classification": "digest", "reason": "r",
                                                  "origin_artifact_id": "SIG-Nope"})
    assert res["isError"] is True


def test_record_notification_without_origin_keeps_only_known_ids(store):
    out = call(store, "record_notification", {"classification": "notify_now", "reason": "HILS が3回続けて失敗",
                                              "impacted_ids": ["TC-HILS-031", "REQ-999"]})
    n = store.get("notifications", out["id"])
    assert n["impacted_ids"] == ["TC-HILS-031"] and n["highlight_ids"] == ["TC-HILS-031"]
    assert n["cross_team_edges"] == []


def test_record_notification_in_quiet_hours_is_held_until_morning(store):
    out = call(store, "record_notification", {"classification": "notify_now", "reason": "R3 に響く",
                                              "origin_artifact_id": SIGNAL_ID})
    assert out["deliver_at"].startswith("2026-11-18T08:00") and out["delivered_at"] is None


def test_start_and_finish_run(store):
    run_id = call(store, "start_run", {"title": "影響の調査", "detail": {"source": "chat"}})["run_id"]
    call(store, "finish_run", {"run_id": run_id, "summary": "モーター制御に影響", "detail": {"classification": "notify_now"}},
         now=NIGHT + timedelta(minutes=5))
    run = store.get("agent_runs", run_id)
    assert run["state"] == "done" and run["finished_at"].startswith("2026-11-17T21:15")
    assert run["detail"] == {"source": "chat", "summary": "モーター制御に影響", "classification": "notify_now"}


def test_finish_run_rejects_other_teams_run(store):
    run_id = call(store, "start_run", {"title": "調査"}, team=MC)["run_id"]
    assert call_raw(store, "finish_run", {"run_id": run_id, "summary": "s"})["isError"] is True
    assert store.get("agent_runs", run_id)["state"] == "running"


def test_finish_unknown_run_is_is_error(store):
    assert call_raw(store, "finish_run", {"run_id": "run-nope", "summary": "s"})["isError"] is True


def test_add_and_remove_watch(store):
    out = call(store, "add_watch", {"kind": "test_failure_streak", "description": "回生協調の HILS 失敗はすぐ",
                                    "delivery": "immediate", "feature": "regen_coord", "streak": 3,
                                    "requested_by": "tanaka"})
    w = store.get("watches", out["id"])
    assert w["team"] == "integrated_control" and w["created_by"] == "tanaka"
    assert call(store, "remove_watch", {"watch_id": out["id"]}) == {"removed": True}
    assert store.get("watches", out["id"]) is None


def test_remove_watch_rejects_other_teams_watch(store):
    wid = call(store, "add_watch", {"kind": "test_failure_streak", "description": "d", "delivery": "digest",
                                    "feature": "regen_coord", "requested_by": "sato"}, team=MC)["id"]
    assert call_raw(store, "remove_watch", {"watch_id": wid})["isError"] is True
    assert store.get("watches", wid) is not None


def test_add_schedule(store):
    out = call(store, "add_schedule", {"due_at": "2026-11-18T15:00:00+09:00", "task": "再試験の結果をもう一度見る",
                                       "payload": {"testcase_id": "TC-HILS-031"}})
    s = store.get("schedules", out["id"])
    assert s["team"] == "integrated_control" and s["done_at"] is None


def test_wrong_type_argument_is_is_error_not_exception(store):
    res = call_raw(store, "create_proposal", {"kind": "impact_notice", "to_teams": "motor_control", "draft": "d"})
    assert res["isError"] is True


def test_missing_required_argument_is_is_error(store):
    assert call_raw(store, "post_message", {})["isError"] is True


def test_begin_morning_digest_once_per_virtual_day(store):
    morning = datetime(2026, 11, 18, 8, 0, tzinfo=JST)
    first = call(store, "begin_morning_digest", {}, now=morning)
    assert first == {"already_done": False, "run_id": "run-morning-integrated_control-20261118"}
    assert call(store, "begin_morning_digest", {}, now=morning + timedelta(minutes=3)) == {"already_done": True}
    assert call(store, "begin_morning_digest", {}, now=morning + timedelta(days=1))["already_done"] is False
    # ほかのチームは別に数える
    assert call(store, "begin_morning_digest", {}, team=MC, now=morning)["already_done"] is False
