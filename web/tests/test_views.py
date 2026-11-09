import json
from datetime import datetime, timedelta

from vehicle_core.constants import JST, VEHICLE_ID

from proactive_web.personas import PERSONAS
from proactive_web.views import build_state, visible_messages
from tests.helpers import MORNING, NIGHT, message, notification, run


def test_held_notification_and_its_message_are_hidden_until_delivered(store):  # Review Focus 4
    store.create("notifications", notification("n-1", delivered_at=None))
    store.create("messages", message("m-1", notification_id="n-1"))
    store.create("messages", message("m-2", created_at=NIGHT + timedelta(minutes=1)))
    state = build_state(store, PERSONAS["tanaka"], NIGHT, [])
    assert [m["id"] for m in state["messages"]] == ["m-2"]
    assert "n-1" not in state["notifications"]
    store.upsert("notifications", store.get("notifications", "n-1") | {"delivered_at": MORNING.isoformat()})
    state = build_state(store, PERSONAS["tanaka"], MORNING, [])
    assert [m["id"] for m in state["messages"]] == ["m-1", "m-2"]  # 古い順
    assert "n-1" in state["notifications"]


def test_message_pointing_to_missing_notification_is_hidden(store):
    store.create("messages", message("m-1", notification_id="n-missing"))
    assert build_state(store, PERSONAS["tanaka"], MORNING, [])["messages"] == []


def test_team_persona_sees_only_own_team_and_chief_sees_all_notifications(store):
    store.create("notifications", notification("n-ic", team="integrated_control", delivered_at=MORNING))
    store.create("notifications", notification("n-ev", team="evaluation", delivered_at=MORNING))
    store.create("messages", message("m-ic", team="integrated_control"))
    store.create("messages", message("m-ce", team="chief_engineer"))
    tanaka = build_state(store, PERSONAS["tanaka"], MORNING, [])
    chief = build_state(store, PERSONAS["takahashi"], MORNING, [])
    assert set(tanaka["notifications"]) == {"n-ic"}
    assert set(chief["notifications"]) == {"n-ic", "n-ev"}
    assert [m["id"] for m in tanaka["messages"]] == ["m-ic"]
    assert [m["id"] for m in chief["messages"]] == ["m-ce"]


def test_release_days_left_uses_virtual_today(store):
    state = build_state(store, PERSONAS["tanaka"], datetime(2026, 11, 17, 18, 0, tzinfo=JST), [])
    assert state["release"] == {"id": "R3", "due_date": "2026-11-30", "days_left": 13}


def test_priority_messages_are_chief_messages_linked_to_notify_now(store):
    store.create("notifications", notification("n-now", team="chief_engineer", delivered_at=MORNING))
    store.create("notifications", notification("n-dig", team="chief_engineer", delivered_at=MORNING,
                                               classification="digest"))
    store.create("messages", message("m-now", team="chief_engineer", notification_id="n-now"))
    store.create("messages", message("m-dig", team="chief_engineer", notification_id="n-dig"))
    store.create("notifications", notification("n-ic", delivered_at=MORNING))
    store.create("messages", message("m-ic", notification_id="n-ic"))
    assert build_state(store, PERSONAS["takahashi"], MORNING, [])["priority_message_ids"] == ["m-now"]
    assert build_state(store, PERSONAS["tanaka"], MORNING, [])["priority_message_ids"] == []


def test_work_groups_runs_and_plans(store):
    now = MORNING
    store.create("agent_runs", run("r-run", state="running", started_at=now - timedelta(minutes=3)))
    store.create("agent_runs", run("r-plan", state="scheduled", started_at=now + timedelta(hours=3), title="再確認"))
    store.create("agent_runs", run("r-old", state="done", started_at=now - timedelta(hours=5),
                                   finished_at=now - timedelta(hours=4), detail={"summary": "古い"}))
    store.create("agent_runs", run("r-new", state="done", started_at=now - timedelta(hours=2),
                                   finished_at=now - timedelta(hours=1), detail={"summary": "新しい"}))
    store.create("agent_runs", run("r-mc", team="motor_control", state="running"))
    store.create("schedules", {"id": "sch-1", "vehicle_id": VEHICLE_ID, "team": "integrated_control",
                               "due_at": (now + timedelta(hours=1)).isoformat(), "task": "再試験の結果を見る",
                               "payload": {}, "done_at": None})
    work = build_state(store, PERSONAS["tanaka"], now, [])["work"]
    assert [r["id"] for r in work["now"]] == ["r-run"]
    assert [p["title"] for p in work["planned"]] == ["再試験の結果を見る", "再確認", "朝のまとめ（Routines）"]
    assert work["planned"][-1]["at"] == datetime(2026, 11, 19, 8, 0, tzinfo=JST).isoformat()
    assert [(r["id"], r["summary"]) for r in work["done"]] == [("r-new", "新しい"), ("r-old", "古い")]
    chief = build_state(store, PERSONAS["takahashi"], now, [])["work"]
    assert {r["id"] for r in chief["now"]} == {"r-run", "r-mc"}
    assert [p["title"] for p in chief["planned"]][-2:] == ["朝のブリーフィング（Routines）", "リリース前の抜け漏れチェック"]


def test_chat_busy_reflects_running_chat_run(store):
    assert build_state(store, PERSONAS["tanaka"], MORNING, [])["chat_busy"] is False
    store.create("agent_runs", run("run-chat-m1", detail={"kind": "chat"}))
    assert build_state(store, PERSONAS["tanaka"], MORNING, [])["chat_busy"] is True
    assert build_state(store, PERSONAS["sato"], MORNING, [])["chat_busy"] is False


def test_state_has_people_settings_watches_and_memories(store):
    memories = [{"id": "mem-1", "text": "連絡は朝まとめて"}]
    state = build_state(store, PERSONAS["suzuki"], MORNING, memories)
    assert state["team"] == "evaluation" and state["team_label"] == "評価"
    assert state["people"]["tanaka"] == "田中"
    assert state["settings"] == {"proactivity": "normal", "quiet_start": "20:00:00", "quiet_end": "08:00:00"}
    assert state["memories"] == memories and state["watches"] == []
    assert state["persona"]["id"] == "suzuki" and state["now"] == MORNING.isoformat()


def test_agent_client_id_is_not_exposed(store):
    ts = store.get("team_settings", "ts-integrated_control")
    store.upsert("team_settings", ts | {"agent_client_id": "secret-client", "chat_conversation_id": "conv-x"})
    text = json.dumps(build_state(store, PERSONAS["takahashi"], MORNING, []), ensure_ascii=False)
    assert "secret-client" not in text and "_etag" not in text


def test_visible_messages_sorts_by_time():
    msgs = [message("b", created_at=MORNING), message("a", created_at=NIGHT)]
    assert [m["id"] for m in visible_messages(msgs, {})] == ["a", "b"]
