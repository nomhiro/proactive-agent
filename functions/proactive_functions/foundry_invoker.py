"""本物の AgentInvoker（Plan 3 決定 10、11、17）。

- 調査の依頼ごとに会話を作り、チームのエージェントに background=True で Responses を送って、受け付けで戻る
- 終わらなかった調査（応答が失敗した、完了したのに finish_run が呼ばれなかった）を tick が片付ける
- 時計を進めて朝 8:00 を越えたときだけ、朝のまとめの Routines を手動で起動する（実時間の 8:00 は cron に任せる）

harness 付きのエージェントは temperature、max_output_tokens、truncation、store、previous_response_id を受け付けない。
送るのは conversation、input、background だけにする（設計書 7.10 節）。
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from vehicle_core.clock import crossed_morning, to_jst
from vehicle_core.constants import VEHICLE_ID, Team, agent_name
from vehicle_core.models import AgentMail, AgentRun, ChangeEvent, MailKind, Proposal, ProposalStatus, Schedule
from vehicle_core.routing import InvestigationRequest

from .docs import parse_each
from .investigations import CONTAINER as INVESTIGATIONS
from .prompts import TRIGGER_LABELS, investigation_prompt
from .store import Conflict, NotFound, Store

log = logging.getLogger(__name__)

RECONCILE_AFTER = timedelta(minutes=2)
FAILED_STATUSES = {"failed", "cancelled", "incomplete"}
LAST_TICK_CONTAINER = "system"
LAST_TICK_ID = "last_tick"


class ResponsesClient(Protocol):
    def create_conversation(self) -> str: ...
    def start_response(self, conversation_id: str, prompt: str) -> str: ...
    def response_status(self, response_id: str) -> str: ...


class FoundryResponsesClient:
    """エージェント1体分。spike の spike_invoke.py と同じ呼び方。"""

    def __init__(self, project_endpoint: str, credential, agent_name: str, *, openai_client=None) -> None:
        self._endpoint = project_endpoint
        self._credential = credential
        self._agent = agent_name
        self._openai = openai_client

    def _client(self):
        if self._openai is None:
            from azure.ai.projects import AIProjectClient
            project = AIProjectClient(endpoint=self._endpoint, credential=self._credential, allow_preview=True)
            self._openai = project.get_openai_client(agent_name=self._agent)
        return self._openai

    def create_conversation(self) -> str:
        return self._client().conversations.create().id

    def start_response(self, conversation_id: str, prompt: str) -> str:
        return self._client().responses.create(conversation=conversation_id, input=prompt, background=True).id

    def response_status(self, response_id: str) -> str:
        return str(self._client().responses.retrieve(response_id).status)


def run_id_for(request_id: str) -> str:
    return f"run-inv-{request_id}"


class FoundryInvoker:
    def __init__(self, store: Store, client_for: Callable[[Team], ResponsesClient],
                 clock: Callable[[], datetime]) -> None:
        self.store = store
        self.client_for = client_for
        self._clock = clock

    def _schedules(self, request: InvestigationRequest) -> list[Schedule]:
        if request.trigger != "schedule":
            return []
        docs = [d for d in (self.store.get("schedules", sid) for sid in request.source_ids) if d]
        return [s for _, s in parse_each(docs, Schedule)]

    def _changes(self, request: InvestigationRequest) -> list[ChangeEvent]:
        if request.trigger != "change":
            return []
        docs = [d for d in (self.store.get("change_events", cid) for cid in request.source_ids) if d]
        return [c for _, c in parse_each(docs, ChangeEvent)]

    def _mails(self, request: InvestigationRequest) -> list[AgentMail]:
        if request.trigger != "mail":
            return []
        # source_ids には、返事の期限切れ（overdue:<thread_id>）のようにメールでない ID も入る。見つからなければ飛ばす
        docs = [d for d in (self.store.get("agent_mail", mid) for mid in request.source_ids) if d]
        return [m for _, m in parse_each(docs, AgentMail)]

    def _proposals(self, request: InvestigationRequest, mails: list[AgentMail]) -> list[Proposal] | None:
        """解析の結果を受けた調査にだけ、起点についての自チームの下書き（却下を除く）を渡す。"""
        if not request.origin_artifact_id or not any(m.kind == MailKind.ANALYSIS_RESULT for m in mails):
            return None
        docs = self.store.query("proposals", {"team": request.team.value})
        return [p for _, p in parse_each(docs, Proposal)
                if p.kind == MailKind.IMPACT_NOTICE and p.status != ProposalStatus.REJECTED
                and request.origin_artifact_id in p.related_artifact_ids]

    def invoke(self, request: InvestigationRequest) -> None:
        run_id = run_id_for(request.id)
        mails = self._mails(request)
        prompt = investigation_prompt(request, run_id, self._schedules(request), self._changes(request),
                                      mails, self._proposals(request, mails))
        client = self.client_for(request.team)
        conversation_id = client.create_conversation()
        response_id = client.start_response(conversation_id, prompt)
        # ここから先の失敗で例外を出すと、起動済みの調査が failed と記録されてしまう。ログに残して戻る
        ids = {"conversation_id": conversation_id, "response_id": response_id}
        try:
            self._record_ids(request.id, ids)
            run = AgentRun(
                id=run_id, team=request.team, state="running",
                title=f"{TRIGGER_LABELS.get(request.trigger, request.trigger)}の調査"
                      + (f"（{request.origin_artifact_id}）" if request.origin_artifact_id else ""),
                started_at=to_jst(self._clock()),
                detail={"investigation_id": request.id, "trigger": request.trigger, **ids},
            )
            self.store.upsert("agent_runs", run.model_dump(mode="json"))
        except Exception:  # noqa: BLE001
            log.exception("investigation started but bookkeeping failed: %s", request.id)

    def _record_ids(self, request_id: str, ids: dict) -> None:
        for _ in range(3):
            current = self.store.get(INVESTIGATIONS, request_id)
            if current is None:
                return
            try:
                self.store.replace(INVESTIGATIONS, current | ids, etag=current["_etag"])
                return
            except (Conflict, NotFound):
                continue


def reconcile_runs(store: Store, client_for: Callable[[Team], ResponsesClient], now: datetime) -> list[str]:
    """running のまま 2 分を過ぎた作業記録の応答を調べ、終わっていれば done にする（決定 11）。チャットの記録は飛ばす。"""
    now = to_jst(now)
    closed = []
    for doc, run in parse_each(store.query("agent_runs", {"state": "running"}), AgentRun):
        response_id = run.detail.get("response_id")
        if run.detail.get("kind") == "chat":
            continue  # チャットの返事は BFF が書き写してから閉じる（Plan 4 決定 6）
        if not response_id or now - to_jst(run.started_at) < RECONCILE_AFTER:
            continue
        try:
            status = client_for(run.team).response_status(response_id)
        except Exception:  # noqa: BLE001 — 1件の失敗で残りを止めない
            log.exception("response status lookup failed: run=%s", run.id)
            continue
        if status in FAILED_STATUSES:
            extra = {"error": status}
        elif status == "completed":
            extra = {"closed_by": "tick"}
        else:
            continue
        done = doc | {"state": "done", "finished_at": now.isoformat(), "detail": {**run.detail, **extra}}
        try:
            store.replace("agent_runs", done, etag=doc["_etag"])
        except (Conflict, NotFound):
            continue  # エージェントの finish_run か別の tick が先に閉じた
        closed.append(run.id)
    return closed


# --- 時計を進めたときの Routines の手動起動（決定 17） --------------------------

class RoutineDispatcher(Protocol):
    def dispatch(self, team: Team) -> None: ...


def routine_name(team: Team) -> str:
    """Routine の名前（Task 10 のデプロイと同じ）。"""
    return f"morning-{agent_name(team)}"


class FoundryRoutineDispatcher:
    """probe_routines.py で確かめた呼び方。会話は指定しない（実行ごとに新しい会話になる）。"""

    def __init__(self, project_endpoint: str, credential, *, project=None) -> None:
        self._endpoint = project_endpoint
        self._credential = credential
        self._project = project

    def dispatch(self, team: Team) -> None:
        if self._project is None:
            from azure.ai.projects import AIProjectClient
            self._project = AIProjectClient(endpoint=self._endpoint, credential=self._credential, allow_preview=True)
        self._project.beta.routines.dispatch(routine_name=routine_name(team))


def _last_tick_doc(now: datetime, offset_seconds: float) -> dict:
    return {"id": LAST_TICK_ID, "vehicle_id": VEHICLE_ID, "at": to_jst(now).isoformat(),
            "offset_seconds": offset_seconds}


def record_clock_baseline(store: Store, now: datetime, offset_seconds: float) -> None:
    """時計を合わせ直したとき（シードの作り直し）に、朝の判定の基準を今のずれにする。

    作り直しは「時計を動かすこと」ではないので、ここで基準を書いておかないと、直後に朝へ進めても起動が抜ける。
    """
    store.upsert(LAST_TICK_CONTAINER, _last_tick_doc(now, offset_seconds))


def morning_dispatch_due(store: Store, now: datetime, offset_seconds: float) -> bool:
    """時計が動かされて朝 8:00 を越えたときだけ真。

    動かす直前の仮想の時刻は「いまの実時間 + 前回のずれ」= now - (今回のずれ - 前回のずれ)。
    last_tick は、ずれが変わったときだけ書く。system コンテナーへの書き込みは tick をもう一度起こすので、
    毎回書くと tick が止まらなくなる。同時に動いた tick は etag で1つだけが勝つ。
    """
    now = to_jst(now)
    doc = store.get(LAST_TICK_CONTAINER, LAST_TICK_ID)
    fresh = _last_tick_doc(now, offset_seconds)
    if doc is None:
        try:
            store.create(LAST_TICK_CONTAINER, fresh)
        except Conflict:
            pass
        return False
    previous = float(doc.get("offset_seconds", 0.0))
    if abs(offset_seconds - previous) < 1.0:
        return False
    try:
        store.replace(LAST_TICK_CONTAINER, doc | fresh, etag=doc["_etag"])
    except (Conflict, NotFound):
        return False  # 別の tick が先に判定した
    return crossed_morning(now - timedelta(seconds=offset_seconds - previous), now)


def dispatch_morning_routines(dispatcher: RoutineDispatcher, teams: list[Team]) -> list[str]:
    started = []
    for team in teams:
        try:
            dispatcher.dispatch(team)
        except Exception:  # noqa: BLE001 — 1体の失敗で残りを止めない
            log.exception("routine dispatch failed: %s", team)
            continue
        started.append(team.value)
    return started
