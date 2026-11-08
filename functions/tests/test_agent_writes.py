"""保存の検査（Plan 2 の書き込み窓口のテストから、HTTP に依らない部分を移したもの）。

401・壊れた本文・405 は MCP の受け口（test_mcp_server.py）が受け持つ。
"""

from datetime import datetime

import pytest
from vehicle_core.constants import JST
from vehicle_core.seed import build_dataset

from proactive_functions.agent_writes import WriteRejected, create_doc, delete_watch, replace_run, team_for_client
from tests.fakes import MemoryStore

NOW = datetime(2026, 11, 17, 21, 20, tzinfo=JST)
DAY = datetime(2026, 11, 18, 10, 0, tzinfo=JST)
IC, MC = "integrated_control", "motor_control"


@pytest.fixture
def store():
    s = MemoryStore()
    ds = build_dataset()
    for a in ds.artifacts:
        s.create("artifacts", a.model_dump(mode="json"))
    for ts in ds.team_settings:
        cid = {IC: "agent-ic", MC: "agent-mc"}.get(ts.team.value)
        s.create("team_settings", ts.model_copy(update={"agent_client_id": cid}).model_dump(mode="json"))
    return s


def msg(**kw):
    return dict(id="m1", vehicle_id="kakuu-suv", team=IC, role="assistant", author="agent",
                text="x", created_at="2026-11-17T00:00:00+09:00") | kw


def notification(**kw):
    return dict(id="n1", vehicle_id="kakuu-suv", team=IC, origin_artifact_id="SIG-BrkPedalPos",
                impacted_ids=[], highlight_ids=[], cross_team_edges=[], classification="notify_now",
                deliver_at="2026-11-17T21:20:00+09:00", reason="R3 に響く",
                created_at="2026-11-17T21:20:00+09:00") | kw


def run_doc(**kw):
    return dict(id="run1", vehicle_id="kakuu-suv", team=IC, state="running", title="影響の調査",
                started_at="2026-11-17T21:20:00+09:00") | kw


def rejected(fn, *args, **kw) -> WriteRejected:
    with pytest.raises(WriteRejected) as e:
        fn(*args, **kw)
    assert e.value.reason
    return e.value


def test_team_for_client(store):
    assert team_for_client(store, "agent-mc") == MC
    assert team_for_client(store, "nobody") is None


def test_unknown_team_is_403(store):
    assert rejected(create_doc, store, None, "messages", msg(), NOW).status == 403


def test_own_message_created_with_gateway_time(store):
    saved = create_doc(store, IC, "messages", msg(), NOW)
    assert saved["created_at"].startswith("2026-11-17T21:20")
    assert store.get("messages", "m1")["created_at"].startswith("2026-11-17T21:20")


def test_existing_id_is_409_and_not_overwritten(store):
    create_doc(store, IC, "messages", msg(text="最初"), NOW)
    assert rejected(create_doc, store, IC, "messages", msg(text="上書き"), NOW).status == 409
    assert store.get("messages", "m1")["text"] == "最初"


def test_impact_notice_by_agent_is_403(store):
    mail = dict(id="am1", vehicle_id="kakuu-suv", thread_id="t", from_team=IC, to_team=MC,
                kind="impact_notice", body="x", created_at="2026-11-17T21:20:00+09:00")
    assert rejected(create_doc, store, IC, "agent_mail", mail, NOW).status == 403


def test_artifacts_write_is_403(store):
    assert rejected(create_doc, store, IC, "artifacts", {"id": "REQ-999"}, NOW).status == 403


def test_night_notification_is_deferred_to_morning(store):
    saved = create_doc(store, IC, "notifications", notification(), NOW)
    assert saved["deliver_at"].startswith("2026-11-18T08:00") and saved["delivered_at"] is None


def test_daytime_notification_is_delivered_now(store):
    saved = create_doc(store, IC, "notifications", notification(), DAY)
    assert saved["deliver_at"].startswith("2026-11-18T10:00")
    assert saved["delivered_at"].startswith("2026-11-18T10:00")


def test_safety_notification_is_immediate_even_at_night(store):
    saved = create_doc(store, IC, "notifications", notification(origin_artifact_id="SR-03"), NOW)
    assert saved["deliver_at"].startswith("2026-11-17T21:20") and saved["delivered_at"] is not None


def test_silent_notification_is_never_delivered(store):
    saved = create_doc(store, IC, "notifications", notification(classification="silent"), DAY)
    assert saved["deliver_at"] is None and saved["delivered_at"] is None


def test_agent_run_update_only_own_team(store):
    create_doc(store, IC, "agent_runs", run_doc(), NOW)
    assert replace_run(store, IC, "run1", run_doc(state="done"), NOW)["state"] == "done"
    assert store.get("agent_runs", "run1")["state"] == "done"
    assert rejected(replace_run, store, MC, "run1", run_doc(), NOW).status == 403
    assert rejected(replace_run, store, IC, "run1", run_doc(id="run2"), NOW).status == 400
    assert rejected(replace_run, store, IC, "nope", run_doc(id="nope"), NOW).status == 404


def test_agent_run_cannot_be_moved_to_other_team(store):
    create_doc(store, IC, "agent_runs", run_doc(), NOW)
    assert rejected(replace_run, store, IC, "run1", run_doc(team=MC), NOW).status == 403


def test_watch_delete_only_own_team(store):
    w = dict(id="w1", vehicle_id="kakuu-suv", team=IC, kind="test_failure_streak", description="d",
             feature="regen_coord", delivery="immediate", created_by="tanaka",
             created_at="2026-11-17T21:20:00+09:00")
    create_doc(store, IC, "watches", w, NOW)
    assert rejected(delete_watch, store, MC, "w1").status == 403
    assert rejected(delete_watch, store, None, "w1").status == 403
    delete_watch(store, IC, "w1")
    assert store.get("watches", "w1") is None
    assert rejected(delete_watch, store, IC, "w1").status == 404
