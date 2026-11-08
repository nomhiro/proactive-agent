"""tick: 仮想時計の「いま」で、時刻に関わる仕事をまとめて進める。

順番（朝の個別の知らせを、朝のまとめより先に届けるため、この順を守る）:
1. 配達: 届ける時刻を過ぎた通知に delivered_at を付け、画面に合図を送る
2. 定時の仕事: 時刻を過ぎた予定から調査依頼を作り、毎日の予定は次の回を作る
3. 返事の期限切れ: 影響の連絡に 48 時間返事がないスレッドで、連絡を出したチームを起こす
4. 受け渡し: not_before を過ぎた調査依頼をまとめてエージェントに渡す
"""

from datetime import datetime, timedelta

from pydantic import BaseModel
from vehicle_core.clock import to_jst
from vehicle_core.escalation import needs_escalation
from vehicle_core.models import AgentMail, Classification, MailKind, Notification, Schedule
from vehicle_core.routing import InvestigationRequest, idempotency_key

from .investigations import AgentInvoker, dispatch_due, enqueue
from .publisher import Publisher, refresh_event
from .store import Conflict, Store


class TickReport(BaseModel):
    delivered_notification_ids: list[str]
    ran_schedule_ids: list[str]
    overdue_thread_ids: list[str]
    dispatched_ids: list[str]


def run_tick(store: Store, invoker: AgentInvoker, publisher: Publisher, now: datetime) -> TickReport:
    now = to_jst(now)
    return TickReport(
        delivered_notification_ids=_deliver(store, publisher, now),
        ran_schedule_ids=_run_schedules(store, now),
        overdue_thread_ids=_overdue_replies(store, now),
        dispatched_ids=dispatch_due(store, invoker, now),
    )


def _deliver(store: Store, publisher: Publisher, now: datetime) -> list[str]:
    delivered = []
    for doc in store.query("notifications", {"delivered_at": None}):
        n = Notification.model_validate(doc)
        if n.deliver_at is None or n.deliver_at > now:
            continue
        try:
            store.replace("notifications", doc | {"delivered_at": now.isoformat()}, etag=doc["_etag"])
        except Conflict:
            continue  # 別の tick が届けた
        publisher.publish(n.team, refresh_event("notifications", n.id, n.team.value))
        delivered.append(n.id)
    return delivered


def next_occurrence(due: datetime, now: datetime) -> datetime:
    """同じ時刻で、now より後の最初の日（たまった日数分は飛ばす）。"""
    days = (now - due) // timedelta(days=1) + 1
    return due + timedelta(days=max(days, 1))


def _run_schedules(store: Store, now: datetime) -> list[str]:
    ran = []
    for doc in store.query("schedules", {"done_at": None}):
        s = Schedule.model_validate(doc)
        if s.due_at > now:
            continue
        try:
            store.replace("schedules", doc | {"done_at": now.isoformat()}, etag=doc["_etag"])
        except Conflict:
            continue  # 別の tick が実行した
        enqueue(store, [InvestigationRequest(
            id=idempotency_key(s.team, "schedule", [s.id]), team=s.team, trigger="schedule",
            origin_artifact_id=None, source_ids=[s.id], impact=None, matched_watch_ids=[],
            floor=Classification.SILENT, not_before=s.due_at,
        )])
        if s.payload.get("recur") == "daily":
            nxt = next_occurrence(to_jst(s.due_at), now)
            series = s.payload.get("series", s.id)
            follow = s.model_copy(update={"id": f"{series}-{nxt:%Y%m%d}", "due_at": nxt, "done_at": None})
            try:
                store.create("schedules", follow.model_dump(mode="json"))
            except Conflict:
                pass
        ran.append(s.id)
    return ran


def _overdue_replies(store: Store, now: datetime) -> list[str]:
    notices = sorted((AgentMail.model_validate(d) for d in store.query("agent_mail", {"kind": MailKind.IMPACT_NOTICE.value})),
                     key=lambda m: m.created_at)
    first_by_thread: dict[str, AgentMail] = {}
    for m in notices:
        first_by_thread.setdefault(m.thread_id, m)
    overdue = []
    for thread_id, first in first_by_thread.items():
        thread = [AgentMail.model_validate(d) for d in store.query("agent_mail", {"thread_id": thread_id})]
        decision = needs_escalation(thread, now)
        if not (decision.escalate and decision.reason == "no_reply"):
            continue
        source_ids = [f"overdue:{thread_id}"]
        created = enqueue(store, [InvestigationRequest(
            id=idempotency_key(first.from_team, "mail", source_ids), team=first.from_team, trigger="mail",
            origin_artifact_id=first.related_artifact_ids[0] if first.related_artifact_ids else None,
            source_ids=source_ids, impact=None, matched_watch_ids=[], floor=Classification.SILENT,
            not_before=now,
        )])
        if created:
            overdue.append(thread_id)
    return overdue
