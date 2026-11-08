"""書き込みの道具（設計書 7.5 節）。

id、team、vehicle_id、created_at、author、role はサーバーが決める（Plan 3 決定 5）。エージェントが渡しても使わない。
保存は agent_writes を通し、vehicle_core.gateway の検査を必ず受ける。
"""

import uuid
from datetime import time, timedelta
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict
from vehicle_core.clock import to_jst
from vehicle_core.constants import DIGEST_TIME, Team
from vehicle_core.impact import analyze_impact
from vehicle_core.models import (
    AgentMail, AgentRun, Classification, DeliveryMode, MailKind, Message, MessageRole, Notification, Proposal,
    Schedule, Stance, Watch, WatchKind,
)

from ..agent_writes import WriteRejected, create_doc, delete_watch, replace_run
from ..handlers import load_graph
from .context import ToolContext, ToolError
from .protocol import Registry, Tool

ASSISTANT_AUTHOR = "agent"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class _Args(BaseModel):
    model_config = ConfigDict(extra="ignore")  # id、team など、サーバーが決める項目は捨てる


def _save(ctx: ToolContext, container: str, model: BaseModel) -> dict:
    try:
        return create_doc(ctx.store, ctx.team.value, container, model.model_dump(mode="json"), ctx.now)
    except WriteRejected as e:
        raise ToolError(e.reason) from None


# --- 会話と提案 -------------------------------------------------------------

class PostMessageArgs(_Args):
    text: str
    notification_id: str | None = None
    proposal_id: str | None = None
    attachments: list[str] = []


def post_message(ctx: ToolContext, args: dict) -> dict:
    a = PostMessageArgs.model_validate(args)
    m = Message(id=new_id("msg"), team=ctx.team, role=MessageRole.ASSISTANT, author=ASSISTANT_AUTHOR, text=a.text,
                notification_id=a.notification_id, proposal_id=a.proposal_id, attachments=a.attachments,
                created_at=ctx.now)
    return {"id": _save(ctx, "messages", m)["id"]}


class CreateProposalArgs(_Args):
    kind: MailKind
    to_teams: list[Team]
    draft: str
    related_artifact_ids: list[str] = []
    thread_id: str | None = None


def create_proposal(ctx: ToolContext, args: dict) -> dict:
    a = CreateProposalArgs.model_validate(args)
    p = Proposal(id=new_id("prop"), team=ctx.team, kind=a.kind, to_teams=a.to_teams, draft=a.draft,
                 related_artifact_ids=a.related_artifact_ids, thread_id=a.thread_id or new_id("th"),
                 created_at=ctx.now)
    saved = _save(ctx, "proposals", p)
    return {"id": saved["id"], "thread_id": saved["thread_id"]}


class SendMailArgs(_Args):
    to_team: Team
    kind: MailKind
    body: str
    related_artifact_ids: list[str] = []
    thread_id: str | None = None
    source_message_id: str | None = None
    stance: Stance | None = None


def send_mail(ctx: ToolContext, args: dict) -> dict:
    a = SendMailArgs.model_validate(args)
    m = AgentMail(id=new_id("am"), thread_id=a.thread_id or new_id("th"), from_team=ctx.team, to_team=a.to_team,
                  kind=a.kind, body=a.body, related_artifact_ids=a.related_artifact_ids,
                  source_message_id=a.source_message_id, stance=a.stance, created_at=ctx.now)
    saved = _save(ctx, "agent_mail", m)
    return {"id": saved["id"], "thread_id": saved["thread_id"]}


# --- 通知 -------------------------------------------------------------------

class RecordNotificationArgs(_Args):
    classification: Classification
    reason: str
    origin_artifact_id: str | None = None
    impacted_ids: list[str] = []


def record_notification(ctx: ToolContext, args: dict) -> dict:
    """根拠（影響を受けるデータ）はコードで求める（Plan 3 決定 6）。"""
    a = RecordNotificationArgs.model_validate(args)
    if a.origin_artifact_id:
        graph = load_graph(ctx.store)
        if not graph.has(a.origin_artifact_id):
            raise ToolError(f"起点のデータがありません: {a.origin_artifact_id}")
        impact = analyze_impact(graph, a.origin_artifact_id)
        impacted, highlight, edges = impact.impacted_ids, impact.highlight_ids, impact.cross_team_edges
    else:
        impacted = [i for i in dict.fromkeys(a.impacted_ids) if ctx.store.get("artifacts", i) is not None]
        highlight, edges = impacted, []
    n = Notification(id=new_id("ntf"), team=ctx.team, origin_artifact_id=a.origin_artifact_id,
                     impacted_ids=impacted, highlight_ids=highlight, cross_team_edges=edges,
                     classification=a.classification, deliver_at=None, reason=a.reason, created_at=ctx.now)
    saved = _save(ctx, "notifications", n)
    return {"id": saved["id"], "deliver_at": saved["deliver_at"], "delivered_at": saved["delivered_at"]}


# --- 作業記録 -----------------------------------------------------------------

class StartRunArgs(_Args):
    title: str
    detail: dict[str, Any] = {}


def start_run(ctx: ToolContext, args: dict) -> dict:
    a = StartRunArgs.model_validate(args)
    run = AgentRun(id=new_id("run"), team=ctx.team, state="running", title=a.title, started_at=ctx.now,
                   detail=a.detail)
    return {"run_id": _save(ctx, "agent_runs", run)["id"]}


class FinishRunArgs(_Args):
    run_id: str
    summary: str
    detail: dict[str, Any] = {}


def finish_run(ctx: ToolContext, args: dict) -> dict:
    a = FinishRunArgs.model_validate(args)
    existing = ctx.store.get("agent_runs", a.run_id)
    if existing is None:
        raise ToolError(f"作業記録がありません: {a.run_id}")
    run = AgentRun.model_validate(existing)
    done = run.model_copy(update={"state": "done", "finished_at": ctx.now,
                                  "detail": {**run.detail, "summary": a.summary, **a.detail}})
    try:
        replace_run(ctx.store, ctx.team.value, a.run_id, done.model_dump(mode="json"), ctx.now)
    except WriteRejected as e:
        raise ToolError(e.reason) from None
    return {"run_id": a.run_id}


MORNING_WINDOW_END = time(12, 0)
STALE_DIGEST_AFTER = timedelta(minutes=15)


def begin_morning_digest(ctx: ToolContext, args: dict) -> dict:
    """朝のまとめを1日1回に限る（Plan 3 決定 9）。仮想の日付とチームで決まる ID を新規作成できたら始めてよい。

    - 仮想の時刻が朝（8:00〜11:59）でなければ作らない。実時間の cron は仮想の時計と関係なく毎朝起動するので、
      仮想の夜中にまとめを作って、その日の本来のまとめを塞がないようにする
    - 前の起動が途中で失敗して running のまま 15 分たっていれば、引き継いでやり直す
    """
    now = to_jst(ctx.now)
    if not (DIGEST_TIME <= now.time() < MORNING_WINDOW_END):
        return {"already_done": True, "not_morning": True}
    run_id = f"run-morning-{ctx.team.value}-{now:%Y%m%d}"
    title = "朝のブリーフィング" if ctx.team == Team.CHIEF_ENGINEER else "朝のまとめ"
    run = AgentRun(id=run_id, team=ctx.team, state="running", title=title, started_at=now)
    try:
        create_doc(ctx.store, ctx.team.value, "agent_runs", run.model_dump(mode="json"), now)
    except WriteRejected as e:
        if e.status != 409:
            raise ToolError(e.reason) from None
        existing = ctx.store.get("agent_runs", run_id)
        if not existing or existing.get("state") != "running"                 or now - to_jst(AgentRun.model_validate(existing).started_at) < STALE_DIGEST_AFTER:
            return {"already_done": True}
        try:
            replace_run(ctx.store, ctx.team.value, run_id, run.model_dump(mode="json"), now)
        except WriteRejected:
            return {"already_done": True}  # 別の起動が先に引き継いだ
    return {"already_done": False, "run_id": run_id}


# --- 見張りと予定 -------------------------------------------------------------

class AddWatchArgs(_Args):
    kind: WatchKind
    description: str
    delivery: DeliveryMode
    requested_by: str
    target_ids: list[str] = []
    feature: str | None = None
    streak: int = 3


def add_watch(ctx: ToolContext, args: dict) -> dict:
    a = AddWatchArgs.model_validate(args)
    w = Watch(id=new_id("w"), team=ctx.team, kind=a.kind, description=a.description, target_ids=a.target_ids,
              feature=a.feature, streak=a.streak, delivery=a.delivery, created_by=a.requested_by,
              created_at=ctx.now)
    return {"id": _save(ctx, "watches", w)["id"]}


class RemoveWatchArgs(_Args):
    watch_id: str


def remove_watch(ctx: ToolContext, args: dict) -> dict:
    a = RemoveWatchArgs.model_validate(args)
    try:
        delete_watch(ctx.store, ctx.team.value, a.watch_id)
    except WriteRejected as e:
        raise ToolError(e.reason) from None
    return {"removed": True}


class AddScheduleArgs(_Args):
    due_at: AwareDatetime
    task: str
    payload: dict[str, Any] = {}


def add_schedule(ctx: ToolContext, args: dict) -> dict:
    a = AddScheduleArgs.model_validate(args)
    s = Schedule(id=new_id("sch"), team=ctx.team, due_at=a.due_at, task=a.task, payload=a.payload)
    return {"id": _save(ctx, "schedules", s)["id"]}


# --- 登録 -------------------------------------------------------------------

def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


_S = {"type": "string"}
_SL = {"type": "array", "items": {"type": "string"}}
_OBJ = {"type": "object"}
_TEAM = {"type": "string", "enum": [t.value for t in Team]}
_KIND = {"type": "string", "enum": [k.value for k in MailKind]}

TOOLS = [
    Tool("post_message", "自チームの会話欄に、アシスタントとしてメッセージを書く。グラフは attachments に "
         "\"foundry-file:<ファイル ID>\" で添付する。通知や提案に結びつけるときは、その ID を渡す。",
         _schema({"text": _S, "notification_id": _S, "proposal_id": _S, "attachments": _SL}, ["text"]), post_message),
    Tool("create_proposal", "人の承認が要る行動の下書きを作る（例: 他チームへの impact_notice）。人が承認すると、決まったコードが実行する。",
         _schema({"kind": _KIND, "to_teams": {"type": "array", "items": _TEAM}, "draft": _S,
                  "related_artifact_ids": _SL, "thread_id": _S}, ["kind", "to_teams", "draft"]), create_proposal),
    Tool("send_mail", "ほかのチームのアシスタントにメールを送る。承認なしで送れる種類（analysis_request、analysis_result、"
         "question、answer、human_reply、escalation）だけ。impact_notice は create_proposal で下書きにする。",
         _schema({"to_team": _TEAM, "kind": _KIND, "body": _S, "related_artifact_ids": _SL, "thread_id": _S,
                  "source_message_id": _S, "stance": {"type": "string", "enum": [s.value for s in Stance]}},
                 ["to_team", "kind", "body"]), send_mail),
    Tool("record_notification", "調査の結論を通知として記録する。classification は silent / digest / notify_now。"
         "origin_artifact_id を渡すと、影響を受けるデータはサーバーが計算する。いつ届けるかはサーバーが決める。",
         _schema({"classification": {"type": "string", "enum": [c.value for c in Classification]}, "reason": _S,
                  "origin_artifact_id": _S, "impacted_ids": _SL}, ["classification", "reason"]), record_notification),
    Tool("start_run", "作業記録を「いま」として始める。返った run_id を finish_run に渡す。",
         _schema({"title": _S, "detail": _OBJ}, ["title"]), start_run),
    Tool("finish_run", "作業記録を「完了」にする。summary に結論と判断の理由を書く。調査の依頼で渡された run_id にも使う。",
         _schema({"run_id": _S, "summary": _S, "detail": _OBJ}, ["run_id", "summary"]), finish_run),
    Tool("begin_morning_digest", "朝のまとめ（統括は朝のブリーフィング）を始める前に必ず呼ぶ。already_done が true なら、"
         "今日の分は済んでいるか、朝（8:00〜11:59）ではないので、何もせずに終える。", _schema({}, []), begin_morning_digest),
    Tool("add_watch", "見張りを足す。kind は artifact_changed（target_ids の変更）か test_failure_streak（feature の試験が streak 回続けて失敗）。"
         "delivery は immediate（すぐ）か digest（朝のまとめ）。requested_by は頼んだ人の ID。",
         _schema({"kind": {"type": "string", "enum": [k.value for k in WatchKind]}, "description": _S,
                  "delivery": {"type": "string", "enum": [d.value for d in DeliveryMode]}, "requested_by": _S,
                  "target_ids": _SL, "feature": _S, "streak": {"type": "integer", "minimum": 1}},
                 ["kind", "description", "delivery", "requested_by"]), add_watch),
    Tool("remove_watch", "自チームの見張りを消す。", _schema({"watch_id": _S}, ["watch_id"]), remove_watch),
    Tool("add_schedule", "後でもう一度確認する予定を入れる。due_at は日本時間の ISO 形式（例: 2026-11-18T15:00:00+09:00）。",
         _schema({"due_at": _S, "task": _S, "payload": _OBJ}, ["due_at", "task"]), add_schedule),
]


def register_write_tools(registry: Registry) -> None:
    for t in TOOLS:
        registry.add(t)

