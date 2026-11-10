"""シナリオテストの期待値（設計書 9 節）。scripts/scenario_test.py が手順ごとに読み直して待つ。

- 文章の中身は判定しない。データ ID に触れているかだけを見る
- 影響範囲（マップの光り方）はコードで決まるので、analyze_impact と完全に一致することを見る
- final=True の期待値は「起きないこと」。ほかの期待値が揃ってから1回だけ判定する
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from vehicle_core.clock import to_jst
from vehicle_core.constants import AGENT_TEAMS, JST, Team
from vehicle_core.impact import Graph, analyze_impact
from vehicle_core.models import Artifact
from vehicle_core.scenarios import SCENARIOS

from proactive_functions.store import Store

from .views import visible_messages

SNAPSHOT_CONTAINERS = ("agent_runs", "notifications", "messages", "proposals", "agent_mail", "watches",
                       "investigations")
IC, MC, EV, CE = (Team.INTEGRATED_CONTROL.value, Team.MOTOR_CONTROL.value, Team.EVALUATION.value,
                  Team.CHIEF_ENGINEER.value)
S1_DELIVER_AT = datetime(2026, 11, 18, 8, 0, tzinfo=JST)
SATO_TEXT = SCENARIOS["s1_signal_period"].steps[3].text


class MemoryReader(Protocol):
    def list(self, team: str) -> list[dict]: ...


@dataclass
class CheckContext:
    store: Store
    memory: MemoryReader | None
    before_ids: dict[str, set[str]]

    def new(self, container: str, where: dict | None = None) -> list[dict]:
        seen = self.before_ids.get(container, set())
        return [d for d in self.store.query(container, where) if d["id"] not in seen]


@dataclass(frozen=True)
class Check:
    name: str
    predicate: Callable[[CheckContext], bool]
    timeout_s: int
    final: bool = False


def snapshot(store: Store) -> dict[str, set[str]]:
    return {c: {d["id"] for d in store.query(c)} for c in SNAPSHOT_CONTAINERS}


# --- 判定の部品 ------------------------------------------------------------------

def _t(value: str | None) -> datetime | None:
    return to_jst(datetime.fromisoformat(value)) if value else None


def _investigation_done(ctx: CheckContext, team: str, origin: str | None = None) -> bool:
    runs = [r for r in ctx.new("agent_runs", {"team": team}) if r["id"].startswith("run-inv-")]
    if origin:
        def origin_of(r: dict) -> str | None:
            inv = ctx.store.get("investigations", (r.get("detail") or {}).get("investigation_id", ""))
            return (inv or {}).get("origin_artifact_id")
        runs = [r for r in runs if origin_of(r) == origin]
    return bool(runs) and all(r.get("state") == "done" for r in runs)


def _notifications(ctx: CheckContext, team: str, *, origin: str | None = None, classification: str | None = None,
                   new_only: bool = False) -> list[dict]:
    docs = ctx.new("notifications", {"team": team}) if new_only else ctx.store.query("notifications", {"team": team})
    return [n for n in docs if (origin is None or n.get("origin_artifact_id") == origin)
            and (classification is None or n.get("classification") == classification)]


def _visible(ctx: CheckContext, team: str, *, new_only: bool = False) -> list[dict]:
    all_notifications = {n["id"]: n for n in ctx.store.query("notifications")}
    docs = ctx.new("messages", {"team": team}) if new_only else ctx.store.query("messages", {"team": team})
    return visible_messages(docs, all_notifications)


def _mentions(messages: list[dict], *ids: str) -> list[dict]:
    return [m for m in messages if all(i in m.get("text", "") for i in ids)]


def _mail(ctx: CheckContext, kind: str, frm: str | None, to: str) -> list[dict]:
    return [m for m in ctx.store.query("agent_mail", {"kind": kind, "to_team": to})
            if frm is None or m.get("from_team") == frm]


def _s1_impact(ctx: CheckContext) -> list[str]:
    graph = Graph.from_artifacts(Artifact.model_validate(a) for a in ctx.store.query("artifacts"))
    return analyze_impact(graph, "SIG-BrkPedalPos").impacted_ids


def _s1_held(ctx: CheckContext) -> bool:
    return any(_t(n.get("deliver_at")) == S1_DELIVER_AT and n.get("delivered_at") is None
               for n in _notifications(ctx, IC, origin="SIG-BrkPedalPos", classification="notify_now"))


def _s1_impact_matches(ctx: CheckContext) -> bool:
    expected = _s1_impact(ctx)
    found = _notifications(ctx, IC, origin="SIG-BrkPedalPos", classification="notify_now")
    return bool(found) and all(sorted(n.get("impacted_ids", [])) == expected for n in found)


def _memory_has(ctx: CheckContext, team: str, word: str) -> bool:
    return ctx.memory is not None and any(word in m.get("text", "") for m in ctx.memory.list(team))


def _morning_done(ctx: CheckContext, day: str) -> bool:
    return all((ctx.store.get("agent_runs", f"run-morning-{t.value}-{day}") or {}).get("state") == "done"
               for t in AGENT_TEAMS)


# --- 期待値 ----------------------------------------------------------------------

EXPECTATIONS: dict[str, list[Check]] = {
    "s1_signal_period#0": [
        Check("統合制御の調査の記録が done", lambda c: _investigation_done(c, IC, "SIG-BrkPedalPos"), 600),
        Check("起点 SIG-BrkPedalPos、notify_now、届けるのは 11/18 08:00 の未配達の通知がある", _s1_held, 600),
        Check("通知の影響範囲がコードの計算と一致する", _s1_impact_matches, 60),
        Check("評価に analysis_request、評価から analysis_result が届く",
              lambda c: bool(_mail(c, "analysis_request", IC, EV)) and bool(_mail(c, "analysis_result", EV, IC)), 600),
        Check("モーター制御宛ての impact_notice の下書き（pending）がある",
              lambda c: any(p.get("kind") == "impact_notice" and MC in p.get("to_teams", [])
                            and p.get("status") == "pending" for p in c.store.query("proposals", {"team": IC})), 600),
        Check("夜のあいだ田中の画面に新しいメッセージが出ない", lambda c: not _visible(c, IC, new_only=True), 1,
              final=True),
    ],
    "s1_signal_period#1": [
        Check("s1 の通知が配達済み",
              lambda c: any(n.get("delivered_at") for n in
                            _notifications(c, IC, origin="SIG-BrkPedalPos", classification="notify_now")), 600),
        Check("田中の画面に提案つきのメッセージがあり、SIG-BrkPedalPos と MDL-MotorTq に触れている",
              lambda c: any(m.get("proposal_id") for m in _mentions(_visible(c, IC), "SIG-BrkPedalPos", "MDL-MotorTq")),
              120),
    ],
    "s1_signal_period#2": [
        Check("impact_notice が統合制御からモーター制御に届く", lambda c: bool(_mail(c, "impact_notice", IC, MC)), 60),
        Check("佐藤の画面にメッセージがあり、MDL-MotorTq に触れている",
              lambda c: bool(_mentions([m for m in _visible(c, MC, new_only=True) if m.get("role") == "assistant"],
                                       "MDL-MotorTq")), 480),
    ],
    "s1_signal_period#3": [
        Check("モーター制御から統合制御へ human_reply（stance cannot、本文は佐藤の発言そのもの）",
              lambda c: any(m.get("stance") == "cannot" and m.get("body") == SATO_TEXT
                            for m in _mail(c, "human_reply", MC, IC)), 360),
        Check("佐藤へのチャットの返事がある",
              lambda c: any(m["id"].startswith("msg-reply-") and m.get("role") == "assistant"
                            for m in c.new("messages", {"team": MC})), 360),
    ],
    "s1_signal_period#4": [
        Check("統括に escalation が届く", lambda c: bool(_mail(c, "escalation", None, CE)), 600),
        Check("高橋の画面に notify_now の通知にひもづくメッセージがあり、MDL-MotorTq に触れている",
              lambda c: any((c.store.get("notifications", m.get("notification_id") or "") or {}).get("classification")
                            == "notify_now" for m in _mentions(_visible(c, CE), "MDL-MotorTq")), 600),
    ],
    "s5_watch_memory#0": [
        Check("統合制御に test_failure_streak（regen_coord、すぐ）の見張りがある",
              lambda c: any(w.get("kind") == "test_failure_streak" and w.get("feature") == "regen_coord"
                            and w.get("delivery") == "immediate" for w in c.store.query("watches", {"team": IC})), 300),
    ],
    "s5_watch_memory#1": [
        Check("統合制御の記憶に「朝」の好みがある", lambda c: _memory_has(c, IC, "朝"), 300),
    ],
    "s5_watch_memory#2": [
        Check("統合制御の記憶から「朝」の好みが消える", lambda c: c.memory is not None and not _memory_has(c, IC, "朝"),
              300),
    ],
    "s2_hils_streak#2": [
        Check("統合制御の調査の記録が done", lambda c: _investigation_done(c, IC), 600),
        Check("統合制御に配達済みの notify_now の通知がある",
              lambda c: any(n.get("delivered_at") for n in _notifications(c, IC, classification="notify_now",
                                                                         new_only=True)), 600),
    ],
    "s0_noise#0": [
        Check("統合制御の調査の記録が done", lambda c: _investigation_done(c, IC, "SPEC-BRK-04"), 480),
        Check("起点 SPEC-BRK-04 の silent 以外の通知がない",
              lambda c: all(n.get("classification") == "silent"
                            for n in _notifications(c, IC, origin="SPEC-BRK-04", new_only=True)), 1, final=True),
        Check("田中の画面に新しいメッセージがない", lambda c: not _visible(c, IC, new_only=True), 1, final=True),
    ],
    "s3_morning#0": [
        Check("4体の朝のまとめ（run-morning-…-20261119）が done", lambda c: _morning_done(c, "20261119"), 900),
    ],
    "s4_release_gap#0": [
        Check("sch-release-gap-R3 が実行済み",
              lambda c: bool((c.store.get("schedules", "sch-release-gap-R3") or {}).get("done_at")), 300),
        Check("統括に R3 に触れたメッセージがある", lambda c: bool(_mentions(_visible(c, CE, new_only=True), "R3")), 600),
    ],
}
