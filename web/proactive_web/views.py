"""画面の状態（決定 9〜12）。Store を読んで、1人の人物から見える分だけを返す。

- 配達前の通知（delivered_at が空）と、それにひもづくメッセージは返さない（Functions の publisher と同じ規則）
- 自チームの分だけ返す。統括（高橋）は、通知と作業と予定だけ全チームの分を返す（設計書 7.5 節の表）
- agent_client_id や Cosmos の内部の項目（_etag など）は返さない
"""

from datetime import date, datetime, timedelta

from proactive_functions.store import Store
from vehicle_core.clock import to_jst
from vehicle_core.constants import DIGEST_TIME, JST, TEAM_LABELS_JA, Team

from .personas import Persona

RELEASE_ID = "R3"
DONE_LIMIT = 20
SCHEDULE_LABELS = {"release_gap_check": "リリース前の抜け漏れチェック"}


def _t(value: str | None) -> datetime:
    return to_jst(datetime.fromisoformat(value)) if value else datetime.min.replace(tzinfo=JST)


def clean(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if not k.startswith("_") and k not in ("origin", "agent_client_id")}


def is_held_message(msg: dict, notifications_by_id: dict[str, dict]) -> bool:
    nid = msg.get("notification_id")
    if not nid:
        return False
    n = notifications_by_id.get(nid)
    return n is None or n.get("delivered_at") is None


def visible_messages(messages: list[dict], notifications_by_id: dict[str, dict]) -> list[dict]:
    shown = [clean(m) for m in messages if not is_held_message(m, notifications_by_id)]
    return sorted(shown, key=lambda m: (_t(m.get("created_at")), m["id"]))


def _release(store: Store, today: date) -> dict | None:
    rel = store.get("artifacts", RELEASE_ID)
    due = (rel or {}).get("attributes", {}).get("due_date")
    if not due:
        return None
    return {"id": RELEASE_ID, "due_date": due, "days_left": (date.fromisoformat(due) - today).days}


def _next_morning(now: datetime) -> datetime:
    first = datetime.combine(now.date(), DIGEST_TIME, tzinfo=JST)
    return first if first > now else first + timedelta(days=1)


def _run_view(r: dict) -> dict:
    return {"id": r["id"], "team": r.get("team"), "title": r.get("title", ""), "state": r.get("state"),
            "started_at": r.get("started_at"), "finished_at": r.get("finished_at"),
            "summary": (r.get("detail") or {}).get("summary")}


def _work(store: Store, team: Team, chief: bool, now: datetime) -> dict:
    where = None if chief else {"team": team.value}
    runs = store.query("agent_runs", where)
    running = sorted((r for r in runs if r.get("state") == "running"), key=lambda r: _t(r.get("started_at")))
    done = sorted((r for r in runs if r.get("state") == "done"),
                  key=lambda r: _t(r.get("finished_at") or r.get("started_at")), reverse=True)[:DONE_LIMIT]
    planned = [{"kind": "run", "team": r.get("team"), "title": r.get("title", ""), "at": r.get("started_at")}
               for r in runs if r.get("state") == "scheduled"]
    planned += [{"kind": "schedule", "team": s.get("team"), "title": SCHEDULE_LABELS.get(s["task"], s["task"]),
                 "at": s.get("due_at")}
                for s in store.query("schedules", where) if not s.get("done_at")]
    routine = "朝のブリーフィング（Routines）" if chief else "朝のまとめ（Routines）"
    planned.append({"kind": "routine", "team": team.value, "title": routine,
                    "at": _next_morning(now).isoformat()})
    planned.sort(key=lambda p: _t(p["at"]))
    return {"now": [_run_view(r) for r in running], "planned": planned, "done": [_run_view(r) for r in done]}


def _settings(store: Store, team: Team) -> dict:
    ts = store.get("team_settings", f"ts-{team.value}") or {}
    return {"proactivity": ts.get("proactivity", "normal"), "quiet_start": ts.get("quiet_start", "20:00:00"),
            "quiet_end": ts.get("quiet_end", "08:00:00")}


def build_state(store: Store, persona: Persona, now: datetime, memories: list[dict]) -> dict:
    now = to_jst(now)
    team = persona.team
    chief = team == Team.CHIEF_ENGINEER
    all_notifications = {n["id"]: n for n in store.query("notifications")}
    notifications = {i: clean(n) for i, n in all_notifications.items()
                     if n.get("delivered_at") and (chief or n.get("team") == team.value)}
    messages = visible_messages(store.query("messages", {"team": team.value}), all_notifications)
    priority = [m["id"] for m in messages
                if chief and (all_notifications.get(m.get("notification_id") or "") or {}).get("classification")
                == "notify_now"]
    people = {p["id"]: p["name_ja"] for ts in store.query("team_settings") for p in ts.get("members", [])}
    chat_busy = any((r.get("detail") or {}).get("kind") == "chat"
                    for r in store.query("agent_runs", {"team": team.value, "state": "running"}))
    return {
        "now": now.isoformat(),
        "release": _release(store, now.date()),
        "persona": persona.as_dict(),
        "team": team.value,
        "team_label": TEAM_LABELS_JA[team],
        "people": people,
        "messages": messages,
        "priority_message_ids": priority,
        "proposals": {p["id"]: clean(p) for p in store.query("proposals", {"team": team.value})},
        "notifications": notifications,
        "work": _work(store, team, chief, now),
        "watches": [clean(w) for w in store.query("watches", {"team": team.value})],
        "memories": memories,
        "settings": _settings(store, team),
        "chat_busy": chat_busy,
    }
