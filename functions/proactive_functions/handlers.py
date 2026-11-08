"""変更フィードの処理: 変更イベント、試験結果、エージェント間メールから調査依頼を作る。

- シード投入・リセットの文書（origin == "seed"）は飛ばす
- 形の壊れた文書はログに残して飛ばし、同じバッチの残りは処理する
  （例外を出すと、同じバッチが永久に再試行される）
"""

import logging
from collections.abc import Iterable
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from vehicle_core.constants import AGENT_TEAMS
from vehicle_core.impact import Graph
from vehicle_core.models import AgentMail, Artifact, ChangeEvent, Classification, MailKind, TestRun, Watch
from vehicle_core.routing import InvestigationRequest, idempotency_key, route_change, route_test_run

from .investigations import enqueue
from .store import Store

log = logging.getLogger(__name__)
M = TypeVar("M", bound=BaseModel)

# 人の承認を経た連絡と、判断の依頼は、人に届けるべきもの（計画の決定6）
_MAIL_FLOOR = {MailKind.IMPACT_NOTICE: Classification.NOTIFY_NOW, MailKind.ESCALATION: Classification.NOTIFY_NOW}


def _valid(docs: Iterable[dict], model: type[M]) -> list[M]:
    out = []
    for d in docs:
        if d.get("origin") == "seed":
            continue
        try:
            out.append(model.model_validate(d))
        except ValidationError as e:
            log.warning("skip invalid %s doc id=%s errors=%d", model.__name__, d.get("id"), e.error_count())
    return out


def _graph(store: Store) -> Graph:
    return Graph.from_artifacts(Artifact.model_validate(d) for d in store.query("artifacts"))


def _watches(store: Store) -> list[Watch]:
    return [Watch.model_validate(d) for d in store.query("watches")]


def handle_change_events(docs: list[dict], store: Store) -> list[str]:
    events = _valid(docs, ChangeEvent)
    if not events:
        return []
    graph, watches = _graph(store), _watches(store)
    return enqueue(store, [r for ev in events for r in route_change(ev, graph, watches)])


def handle_test_runs(docs: list[dict], store: Store) -> list[str]:
    runs = _valid(docs, TestRun)
    if not runs:
        return []
    graph, watches = _graph(store), _watches(store)
    created = []
    for run in runs:
        history = [TestRun.model_validate(d) for d in store.query("test_runs", {"feature": run.feature})
                   if d["id"] != run.id]
        created += enqueue(store, route_test_run(run, history, graph, watches))
    return created


def mail_request(mail: AgentMail) -> InvestigationRequest | None:
    if mail.to_team not in AGENT_TEAMS:
        return None
    return InvestigationRequest(
        id=idempotency_key(mail.to_team, "mail", [mail.id]),
        team=mail.to_team,
        trigger="mail",
        origin_artifact_id=mail.related_artifact_ids[0] if mail.related_artifact_ids else None,
        source_ids=[mail.id],
        impact=None,
        matched_watch_ids=[],
        floor=_MAIL_FLOOR.get(mail.kind, Classification.SILENT),
        not_before=mail.created_at,
    )


def handle_agent_mail(docs: list[dict], store: Store) -> list[str]:
    requests = [r for m in _valid(docs, AgentMail) if (r := mail_request(m)) is not None]
    return enqueue(store, requests)
