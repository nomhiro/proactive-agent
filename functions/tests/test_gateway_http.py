import json
from datetime import datetime

import pytest
from vehicle_core.constants import JST
from vehicle_core.seed import build_dataset

from proactive_functions.gateway_http import handle_agent_write, team_for_client
from tests.fakes import FakeVerifier, MemoryStore

NOW = datetime(2026, 11, 17, 21, 20, tzinfo=JST)
DAY = datetime(2026, 11, 18, 10, 0, tzinfo=JST)


@pytest.fixture
def store():
    s = MemoryStore()
    ds = build_dataset()
    for a in ds.artifacts:
        s.create("artifacts", a.model_dump(mode="json"))
    for ts in ds.team_settings:
        cid = {"integrated_control": "agent-ic", "motor_control": "agent-mc"}.get(ts.team.value)
        s.create("team_settings", ts.model_copy(update={"agent_client_id": cid}).model_dump(mode="json"))
    return s


def call(store, method, container, body=None, item_id=None, client="agent-ic", now=NOW, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    return handle_agent_write(method, container, item_id, f"Bearer {client}" if client else None, data,
                              store=store, verifier=FakeVerifier(), now=now)


def msg(**kw):
    return dict(id="m1", vehicle_id="kakuu-suv", team="integrated_control", role="assistant", author="agent",
                text="x", created_at="2026-11-17T00:00:00+09:00") | kw


def notification(**kw):
    return dict(id="n1", vehicle_id="kakuu-suv", team="integrated_control", origin_artifact_id="SIG-BrkPedalPos",
                impacted_ids=[], highlight_ids=[], cross_team_edges=[], classification="notify_now",
                deliver_at="2026-11-17T21:20:00+09:00", reason="R3 に響く",
                created_at="2026-11-17T21:20:00+09:00") | kw


def run_doc(**kw):
    return dict(id="run1", vehicle_id="kakuu-suv", team="integrated_control", state="running", title="影響の調査",
                started_at="2026-11-17T21:20:00+09:00") | kw


def test_team_for_client(store):
    assert team_for_client(store, "agent-mc") == "motor_control"
    assert team_for_client(store, "nobody") is None


def test_no_token_is_401(store):
    assert call(store, "POST", "messages", msg(), client=None).status == 401


def test_unknown_client_is_403(store):  # 正しい aud でも対応表にないアプリは拒否
    r = call(store, "POST", "messages", msg(), client="some-other-app")
    assert r.status == 403 and r.body["reason"]


def test_bad_json_is_400(store):
    assert call(store, "POST", "messages", raw=b"{not json").status == 400


def test_own_message_created_with_gateway_time(store):
    r = call(store, "POST", "messages", msg())
    assert r.status == 201 and r.body["created_at"].startswith("2026-11-17T21:20")
    assert store.get("messages", "m1")["created_at"].startswith("2026-11-17T21:20")


def test_existing_id_is_409_and_not_overwritten(store):
    call(store, "POST", "messages", msg(text="最初"))
    r = call(store, "POST", "messages", msg(text="上書き"))
    assert r.status == 409 and r.body["reason"]
    assert store.get("messages", "m1")["text"] == "最初"


def test_impact_notice_by_agent_is_403(store):
    mail = dict(id="am1", vehicle_id="kakuu-suv", thread_id="t", from_team="integrated_control",
                to_team="motor_control", kind="impact_notice", body="x", created_at="2026-11-17T21:20:00+09:00")
    assert call(store, "POST", "agent_mail", mail).status == 403


def test_artifacts_write_is_403(store):
    assert call(store, "POST", "artifacts", {"id": "REQ-999"}).status == 403


def test_night_notification_is_deferred_to_morning(store):
    r = call(store, "POST", "notifications", notification())
    assert r.status == 201
    assert r.body["deliver_at"].startswith("2026-11-18T08:00") and r.body["delivered_at"] is None


def test_daytime_notification_is_delivered_now(store):
    r = call(store, "POST", "notifications", notification(), now=DAY)
    assert r.body["deliver_at"].startswith("2026-11-18T10:00")
    assert r.body["delivered_at"].startswith("2026-11-18T10:00")


def test_safety_notification_is_immediate_even_at_night(store):
    r = call(store, "POST", "notifications", notification(origin_artifact_id="SR-03"))
    assert r.body["deliver_at"].startswith("2026-11-17T21:20") and r.body["delivered_at"] is not None


def test_silent_notification_is_never_delivered(store):
    r = call(store, "POST", "notifications", notification(classification="silent"), now=DAY)
    assert r.body["deliver_at"] is None and r.body["delivered_at"] is None


def test_agent_run_update_only_own_team(store):
    assert call(store, "POST", "agent_runs", run_doc()).status == 201
    assert call(store, "PUT", "agent_runs", run_doc(state="done"), item_id="run1").status == 200
    assert store.get("agent_runs", "run1")["state"] == "done"
    assert call(store, "PUT", "agent_runs", run_doc(), item_id="run1", client="agent-mc").status == 403
    assert call(store, "PUT", "agent_runs", run_doc(id="run2"), item_id="run1").status == 400
    assert call(store, "PUT", "agent_runs", run_doc(id="nope"), item_id="nope").status == 404


def test_agent_run_cannot_be_moved_to_other_team(store):
    call(store, "POST", "agent_runs", run_doc())
    assert call(store, "PUT", "agent_runs", run_doc(team="motor_control"), item_id="run1").status == 403


def test_watch_delete_only_own_team(store):
    w = dict(id="w1", vehicle_id="kakuu-suv", team="integrated_control", kind="test_failure_streak",
             description="d", feature="regen_coord", delivery="immediate", created_by="tanaka",
             created_at="2026-11-17T21:20:00+09:00")
    assert call(store, "POST", "watches", w).status == 201
    assert call(store, "DELETE", "watches", item_id="w1", client="agent-mc").status == 403
    assert call(store, "DELETE", "watches", item_id="w1", client="nobody").status == 403
    assert call(store, "DELETE", "watches", item_id="w1").status == 204
    assert store.get("watches", "w1") is None
    assert call(store, "DELETE", "watches", item_id="w1").status == 404


@pytest.mark.parametrize("method,container,item_id", [("PUT", "messages", "m1"), ("DELETE", "messages", "m1"),
                                                      ("POST", "agent_runs", "run1"), ("GET", "messages", None)])
def test_other_combinations_are_405(store, method, container, item_id):
    assert call(store, method, container, msg(), item_id=item_id).status == 405
