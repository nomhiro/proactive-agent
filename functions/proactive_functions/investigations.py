"""調査依頼の記録（investigations コンテナー）と、エージェントへの受け渡し。

依頼の ID は冪等キー。新規作成のみなので、同じ変更が二度届いても記録は1件にとどまる。
tick が not_before を過ぎたものを coalesce してから、AgentInvoker に渡す。
"""

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime
from vehicle_core.clock import to_jst
from vehicle_core.routing import InvestigationRequest, coalesce

from .docs import parse_each
from .store import Conflict, NotFound, Store

CONTAINER = "investigations"
log = logging.getLogger(__name__)


class InvestigationRecord(InvestigationRequest):
    status: Literal["pending", "dispatched", "merged", "failed"] = "pending"
    merged_into: str | None = None
    dispatched_at: AwareDatetime | None = None
    error: str | None = None
    # FoundryInvoker が起動した会話と応答（Plan 3 決定 10）
    conversation_id: str | None = None
    response_id: str | None = None


class AgentInvoker(Protocol):
    def invoke(self, request: InvestigationRequest) -> None: ...


class LoggingInvoker:
    """Plan 2 の受け渡し: ログに出すだけ。本物（Foundry のエージェントを起動する）は Plan 3。"""

    def invoke(self, request: InvestigationRequest) -> None:
        log.info("investigation dispatched: team=%s trigger=%s id=%s source_ids=%s",
                 request.team, request.trigger, request.id, request.source_ids)


def enqueue(store: Store, requests: Iterable[InvestigationRequest]) -> list[str]:
    created = []
    for r in requests:
        record = InvestigationRecord(**r.model_dump())
        try:
            store.create(CONTAINER, record.model_dump(mode="json"))
        except Conflict:
            continue
        created.append(r.id)
    return created


def _members(merged: InvestigationRequest, records: list[dict]) -> list[dict]:
    by_id = {r["id"]: r for r in records}
    if merged.id in by_id:
        return [by_id[merged.id]]
    sources = set(merged.source_ids)
    return [
        r for r in records
        if r["trigger"] == merged.trigger and r["team"] == merged.team
        and r["origin_artifact_id"] == merged.origin_artifact_id and set(r["source_ids"]) <= sources
    ]


def dispatch_due(store: Store, invoker: AgentInvoker, now: datetime) -> list[str]:
    now = to_jst(now)
    stamp = now.isoformat()
    parsed = parse_each(store.query(CONTAINER, {"status": "pending"}), InvestigationRequest)
    records = [d for d, _ in parsed]
    requests = [r for _, r in parsed]
    dispatched = []
    for merged in coalesce(requests):
        if merged.not_before > now:
            continue
        members = _members(merged, records)
        if len(members) == 1 and members[0]["id"] == merged.id:
            # 1件だけ: 元の記録を etag 付きで書き換えて確保する
            m = members[0]
            try:
                store.replace(CONTAINER, m | {"status": "dispatched", "dispatched_at": stamp}, etag=m["_etag"])
            except (Conflict, NotFound):
                log.info("investigation claim lost: %s", merged.id)
                continue
        else:
            # 複数をまとめた: まとめた記録の新規作成を確保とする（先に作れた tick だけが渡す）。
            # 元の記録の印付けは、勝ち負けに関係なく後から行う（途中で止まっても取りこぼさない）
            record = InvestigationRecord(**merged.model_dump(), status="dispatched", dispatched_at=now)
            try:
                store.create(CONTAINER, record.model_dump(mode="json"))
                won = True
            except Conflict:
                won = False
            for m in members:
                try:
                    store.replace(CONTAINER, m | {"status": "merged", "merged_into": merged.id}, etag=m["_etag"])
                except (Conflict, NotFound):
                    pass
            if not won:
                log.info("investigation claim lost: %s", merged.id)
                continue
        try:
            invoker.invoke(merged)
        except Exception as e:  # noqa: BLE001 — 受け渡しの失敗は記録して次へ進む
            log.exception("investigation invoke failed: %s", merged.id)
            current = store.get(CONTAINER, merged.id)
            if current:
                store.replace(CONTAINER, current | {"status": "failed", "error": str(e)}, etag=current["_etag"])
            continue
        dispatched.append(merged.id)
    return dispatched
