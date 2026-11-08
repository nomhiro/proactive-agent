"""書き込み窓口の HTTP 処理（設計書 7.5 節）。

- 呼び出し元のチームは、トークンの client ID と team_settings.agent_client_id の対応表で決める
- 検査は vehicle_core.gateway.authorize_agent_write。保存するのは、その戻り値のモデル
- 保存は新規作成のみ。上書きしてよいのは自チームの agent_runs の置き換えと、自チームの watches の削除だけ
- 通知の deliver_at はコードが決め直す（静かな時間帯、安全要求、チームの設定）
"""

import json
from datetime import datetime

from pydantic import BaseModel
from vehicle_core.clock import to_jst
from vehicle_core.gateway import WriteDenied, authorize_agent_write
from vehicle_core.impact import analyze_impact
from vehicle_core.models import AgentMail, Message, Notification, TeamSettings
from vehicle_core.notify_policy import decide_delivery

from .auth import AuthError, TokenVerifier
from .handlers import load_graph
from .store import Conflict, Store


class HttpResult(BaseModel):
    status: int
    body: dict | None = None


def _reason(status: int, reason: str) -> HttpResult:
    return HttpResult(status=status, body={"reason": reason})


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


def _parse(body: bytes) -> dict | None:
    try:
        doc = json.loads(body or b"null")
    except (ValueError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _authorize(store: Store, team: str | None, container: str, doc: dict, now: datetime) -> BaseModel:
    def lookup_message(id_: str) -> Message | None:
        d = store.get("messages", id_)
        return Message.model_validate(d) if d else None

    def lookup_thread(thread_id: str) -> list[AgentMail]:
        return [AgentMail.model_validate(d) for d in store.query("agent_mail", {"thread_id": thread_id})]

    return authorize_agent_write(team, container, doc, lookup_message, lookup_thread=lookup_thread, now=now)


def handle_agent_write(
    method: str,
    container: str,
    item_id: str | None,
    authorization: str | None,
    body: bytes,
    *,
    store: Store,
    verifier: TokenVerifier,
    now: datetime,
) -> HttpResult:
    now = to_jst(now)
    method = method.upper()
    try:
        client_id = verifier.verify(authorization)
    except AuthError as e:
        return _reason(401, e.reason)
    team = team_for_client(store, client_id)

    if method == "POST" and item_id is None:
        return _create(store, team, container, body, now)
    if method == "PUT" and container == "agent_runs" and item_id:
        return _replace_run(store, team, item_id, body, now)
    if method == "DELETE" and container == "watches" and item_id:
        return _delete_watch(store, team, item_id)
    return _reason(405, "この操作はできません")


def _create(store: Store, team: str | None, container: str, body: bytes, now: datetime) -> HttpResult:
    doc = _parse(body)
    if doc is None:
        return _reason(400, "本文が JSON のオブジェクトではありません")
    try:
        model = _authorize(store, team, container, doc, now)
    except WriteDenied as e:
        return _reason(403, e.reason)
    if isinstance(model, Notification):
        model = _schedule_delivery(store, model, now)
    saved = model.model_dump(mode="json")
    try:
        store.create(container, saved)
    except Conflict:
        return _reason(409, "同じ ID の文書が既にあります")
    return HttpResult(status=201, body=saved)


def _replace_run(store: Store, team: str | None, item_id: str, body: bytes, now: datetime) -> HttpResult:
    existing = store.get("agent_runs", item_id)
    if existing is None:
        return _reason(404, "作業記録がありません")
    if team is None or existing["team"] != team:
        return _reason(403, "ほかのチームの作業記録は書き換えられません")
    doc = _parse(body)
    if doc is None:
        return _reason(400, "本文が JSON のオブジェクトではありません")
    if doc.get("id") != item_id:
        return _reason(400, "本文の id が URL と違います")
    try:
        model = _authorize(store, team, "agent_runs", doc, now)
    except WriteDenied as e:
        return _reason(403, e.reason)
    saved = model.model_dump(mode="json")
    try:
        store.replace("agent_runs", saved, etag=existing["_etag"])
    except Conflict:
        return _reason(409, "作業記録が先に更新されました")
    return HttpResult(status=200, body=saved)


def _delete_watch(store: Store, team: str | None, item_id: str) -> HttpResult:
    if team is None:
        return _reason(403, "呼び出し元のチームがわかりません")
    existing = store.get("watches", item_id)
    if existing is None:
        return _reason(404, "見張りがありません")
    if existing["team"] != team:
        return _reason(403, "ほかのチームの見張りは消せません")
    store.delete("watches", item_id)
    return HttpResult(status=204)
