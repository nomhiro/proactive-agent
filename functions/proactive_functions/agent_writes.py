"""エージェントの書き込みの保存（設計書 7.5 節）。MCP の書き込みの道具から呼ぶ。

- 呼び出し元のチームは、トークンの client ID と team_settings.agent_client_id の対応表で決める
- 検査は vehicle_core.gateway.authorize_agent_write。保存するのは、その戻り値のモデル
- 保存は新規作成のみ。上書きしてよいのは自チームの agent_runs の置き換えと、自チームの watches の削除だけ
- 通知の deliver_at はコードが決め直す（静かな時間帯、安全要求、チームの設定）
"""

from datetime import datetime

from pydantic import BaseModel
from vehicle_core.clock import to_jst
from vehicle_core.gateway import WriteDenied, authorize_agent_write
from vehicle_core.impact import analyze_impact
from vehicle_core.models import AgentMail, Message, Notification, TeamSettings
from vehicle_core.notify_policy import decide_delivery

from .handlers import load_graph
from .store import Conflict, Store


class WriteRejected(Exception):
    """書き込みの拒否。status は HTTP 相当の数値（403、404、409 など）、reason は日本語の理由。"""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def team_for_client(store: Store, client_id: str) -> str | None:
    found = store.query("team_settings", {"agent_client_id": client_id})
    return found[0]["team"] if found else None


def _settings(store: Store, team: str) -> TeamSettings:
    found = store.query("team_settings", {"team": team})
    return TeamSettings.model_validate(found[0]) if found else TeamSettings(id=f"ts-{team}", team=team)


def _schedule_delivery(store: Store, n: Notification, now: datetime) -> Notification:
    graph = load_graph(store)
    touches = bool(n.origin_artifact_id and graph.has(n.origin_artifact_id)
                   and analyze_impact(graph, n.origin_artifact_id).touches_safety)
    decision = decide_delivery(n.classification, touches, now, _settings(store, n.team.value))
    delivered = now if decision.deliver_at is not None and decision.deliver_at <= now else None
    return n.model_copy(update={"deliver_at": decision.deliver_at, "delivered_at": delivered})


def _authorize(store: Store, team: str | None, container: str, doc: dict, now: datetime) -> BaseModel:
    def lookup_message(id_: str) -> Message | None:
        d = store.get("messages", id_)
        return Message.model_validate(d) if d else None

    def lookup_thread(thread_id: str) -> list[AgentMail]:
        return [AgentMail.model_validate(d) for d in store.query("agent_mail", {"thread_id": thread_id})]

    try:
        return authorize_agent_write(team, container, doc, lookup_message, lookup_thread=lookup_thread, now=now)
    except WriteDenied as e:
        raise WriteRejected(403, e.reason) from None


def create_doc(store: Store, team: str | None, container: str, doc: dict, now: datetime) -> dict:
    """検査を通った文書を新規作成し、保存した中身を返す。"""
    now = to_jst(now)
    model = _authorize(store, team, container, doc, now)
    if isinstance(model, Notification):
        model = _schedule_delivery(store, model, now)
    saved = model.model_dump(mode="json")
    try:
        store.create(container, saved)
    except Conflict:
        raise WriteRejected(409, "同じ ID の文書が既にあります") from None
    return saved


def replace_run(store: Store, team: str | None, run_id: str, doc: dict, now: datetime) -> dict:
    """自チームの作業記録を置き換える（「いま → 完了」の更新）。"""
    now = to_jst(now)
    existing = store.get("agent_runs", run_id)
    if existing is None:
        raise WriteRejected(404, "作業記録がありません")
    if team is None or existing["team"] != team:
        raise WriteRejected(403, "ほかのチームの作業記録は書き換えられません")
    if doc.get("id") != run_id:
        raise WriteRejected(400, "本文の id が作業記録の ID と違います")
    model = _authorize(store, team, "agent_runs", doc, now)
    saved = model.model_dump(mode="json")
    try:
        store.replace("agent_runs", saved, etag=existing["_etag"])
    except Conflict:
        raise WriteRejected(409, "作業記録が先に更新されました") from None
    return saved


def delete_watch(store: Store, team: str | None, watch_id: str) -> None:
    """自チームの見張りを消す（「忘れて」）。"""
    if team is None:
        raise WriteRejected(403, "呼び出し元のチームがわかりません")
    existing = store.get("watches", watch_id)
    if existing is None:
        raise WriteRejected(404, "見張りがありません")
    if existing["team"] != team:
        raise WriteRejected(403, "ほかのチームの見張りは消せません")
    store.delete("watches", watch_id)
