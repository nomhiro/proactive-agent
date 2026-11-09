"""ローカルでの確認（決定 20）。Azure に触れずに画面を動かす。

  uv run --package proactive-web python -m proactive_web.dev

メモリーの Store にシードと「シナリオ1の朝」の状態（配達済みの通知、承認待ちの提案、提案つきのメッセージ）を入れる。
通知の根拠は analyze_impact で求める（マップの光り方がコードの計算と一致するように）。
"""

from datetime import datetime, timedelta

from proactive_functions.clock import StoredClock, set_virtual_now
from proactive_functions.memory_store import MemoryStore
from proactive_functions.seeding import seed_store
from vehicle_core.constants import JST, VEHICLE_ID
from vehicle_core.impact import Graph, analyze_impact
from vehicle_core.models import Artifact

DEV_NOW = datetime(2026, 11, 18, 8, 5, tzinfo=JST)
NIGHT = datetime(2026, 11, 17, 21, 25, tzinfo=JST)
MORNING = datetime(2026, 11, 18, 8, 0, tzinfo=JST)


class LocalChatClient:
    """すぐに completed になり、決まった返事を返す偽物（Azure に触れない）。"""

    def __init__(self) -> None:
        self._count = 0

    def create_conversation(self, team) -> str:
        return f"conv-local-{team}"

    def start_response(self, team, conversation_id: str, prompt: str) -> str:
        self._count += 1
        return f"resp-local-{self._count}"

    def get_response(self, team, response_id: str) -> tuple[str, str]:
        return "completed", "（ローカルの確認用の返事です）"


class StaticMemory:
    def __init__(self, items: dict[str, list[dict]]) -> None:
        self._items = items

    def list(self, team: str) -> list[dict]:
        return list(self._items.get(team, []))


def _doc(**fields) -> dict:
    return {"vehicle_id": VEHICLE_ID, **fields}


def add_s1_morning(store: MemoryStore) -> None:
    graph = Graph.from_artifacts(Artifact.model_validate(a) for a in store.query("artifacts"))
    impact = analyze_impact(graph, "SIG-BrkPedalPos")
    store.upsert("notifications", _doc(
        id="n-dev-s1", team="integrated_control", origin_artifact_id="SIG-BrkPedalPos",
        impacted_ids=impact.impacted_ids, highlight_ids=impact.highlight_ids,
        cross_team_edges=[list(e) for e in impact.cross_team_edges], classification="notify_now",
        deliver_at=MORNING.isoformat(), delivered_at=MORNING.isoformat(),
        reason="R3 対象のモデル2つとテスト6件に響くため、すぐ知らせる（夜間のため朝まで保留）",
        created_at=NIGHT.isoformat()))
    store.upsert("proposals", _doc(
        id="prop-dev-s1", team="integrated_control", kind="impact_notice", to_teams=["motor_control"],
        draft="SIG-BrkPedalPos の周期が 10ms から 20ms に変わりました。MDL-MotorTq（v2.0）は 10ms を前提にしており、"
              "TC-HILS-012 の結果に響く見込みです。評価の解析では、回生の立ち上がりが約 15ms 遅れます。確認をお願いします。",
        related_artifact_ids=["SIG-BrkPedalPos", "MDL-MotorTq"], thread_id="th-dev-s1", status="pending",
        decided_by=None, decided_at=None, created_at=NIGHT.isoformat()))
    store.upsert("messages", _doc(
        id="msg-dev-s1", team="integrated_control", role="assistant", author="agent",
        text="昨夜 21:10 に SIG-BrkPedalPos の周期が 10ms から 20ms に変わりました。自チームの MDL-RegenCoord と"
             " TC-HILS-031〜035、モーター制御の MDL-MotorTq と TC-HILS-012 が影響を受けます。"
             "モーター制御への影響の連絡を送ってよいですか。",
        notification_id="n-dev-s1", proposal_id="prop-dev-s1", attachments=[],
        created_at=MORNING.isoformat()))
    store.upsert("agent_runs", _doc(
        id="run-dev-s1", team="integrated_control", state="done", title="変更の調査（SIG-BrkPedalPos）",
        started_at=(NIGHT - timedelta(minutes=14)).isoformat(), finished_at=NIGHT.isoformat(),
        detail={"summary": "notify_now。R3 に響く。モーター制御に影響の連絡の下書きを作った"}))
    store.upsert("watches", _doc(
        id="w-dev-1", team="integrated_control", kind="test_failure_streak", description="回生協調の HILS が落ちたらすぐ",
        target_ids=[], feature="regen_coord", streak=3, delivery="immediate", created_by="tanaka",
        created_at=(NIGHT - timedelta(days=1)).isoformat()))


def dev_store(system_now: datetime | None = None) -> MemoryStore:
    store = MemoryStore()
    real = system_now or datetime.now(JST)
    seed_store(store, reset=False, system_now=real)
    set_virtual_now(store, DEV_NOW, real)
    add_s1_morning(store)
    return store


def dev_deps(auth_mode: str = "off"):
    from .app import Deps
    store = dev_store()
    memory = StaticMemory({"integrated_control": [{"id": "mem-dev-1", "text": "連絡は朝まとめてほしい（急ぎでないもの）"}]})
    from .chat import ChatService
    clock = StoredClock(store)
    return Deps(store=store, clock=clock, memory=memory, chat=ChatService(store, LocalChatClient(), clock.now),
                auth_mode=auth_mode)


def main() -> None:
    import uvicorn

    from .app import create_app
    uvicorn.run(create_app(dev_deps()), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
