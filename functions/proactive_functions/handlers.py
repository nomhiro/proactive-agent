"""変更フィードの処理: 変更イベント、試験結果、エージェント間メールから調査依頼を作る。

- シード投入・リセットの文書（origin == "seed"）は飛ばす
- 形の壊れた文書はログに残して飛ばし、同じバッチの残りは処理する。保存済みの文書
  （artifacts、watches、試験結果の履歴）も同じく、壊れたものだけ飛ばす
- Cosmos のトリガーは、既定では例外の出たバッチを再試行せずに読み飛ばす。一時的な失敗で
  バッチを失わないよう、function_app.py で再試行の設定を付けている（処理は冪等なので安全）
"""

from vehicle_core.constants import AGENT_TEAMS
from vehicle_core.impact import Graph
from vehicle_core.models import AgentMail, Artifact, ChangeEvent, Classification, MailKind, TestRun, Watch
from vehicle_core.routing import InvestigationRequest, idempotency_key, route_change, route_test_run

from .docs import models
from .investigations import enqueue
from .store import Store

# 人の承認を経た連絡と、判断の依頼は、人に届けるべきもの（計画の決定6）
_MAIL_FLOOR = {MailKind.IMPACT_NOTICE: Classification.NOTIFY_NOW, MailKind.ESCALATION: Classification.NOTIFY_NOW}


def load_graph(store: Store) -> Graph:
    return Graph.from_artifacts(models(store.query("artifacts"), Artifact))


def _watches(store: Store) -> list[Watch]:
    return models(store.query("watches"), Watch)


def handle_change_events(docs: list[dict], store: Store) -> list[str]:
    events = models(docs, ChangeEvent, skip_seed=True)
    if not events:
        return []
    graph, watches = load_graph(store), _watches(store)
    return enqueue(store, [r for ev in events for r in route_change(ev, graph, watches)])


def handle_test_runs(docs: list[dict], store: Store) -> list[str]:
    runs = models(docs, TestRun, skip_seed=True)
    if not runs:
        return []
    graph, watches = load_graph(store), _watches(store)
    created = []
    for run in runs:
        history = [r for r in models(store.query("test_runs", {"feature": run.feature}), TestRun)
                   if r.id != run.id]
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
    requests = [r for m in models(docs, AgentMail, skip_seed=True) if (r := mail_request(m)) is not None]
    return enqueue(store, requests)
