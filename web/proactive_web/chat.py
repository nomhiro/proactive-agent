"""チャット（決定 3〜6、設計書 7.8 節）。

- 会話はチームに1本（team_settings.chat_conversation_id）。なければ最初のチャットで作る
- 人の発言を messages に書き、決まった形のプロンプトを background=True で送り、作業記録 run-chat-<発言 ID> を作って戻る
- 返事の受け取りは sync。画面の読み直し（/api/state）と CLI が呼ぶ。裏で待ち続ける処理は持たない
- 返事待ちのあいだは、そのチームの新しいチャットを受け付けない（ChatBusy）。送る処理のあいだは
  system/chat-claim-<チーム> を新規作成して確保し、同時に送られた2つ目をはじく。確保は送り終えたら消す。
  送る途中で止まって残った確保は、CLAIM_STALE を過ぎたら無視する
- 返事の待ち時間（REPLY_TIMEOUT）は実時間で測る。シナリオの手順は仮想の時計だけを大きく進めるため
- エージェントへの要求に入れるのは conversation、input、background だけ（harness が管理する項目は送らない）
"""

import functools
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from proactive_functions.store import Conflict, NotFound, Store
from vehicle_core.clock import to_jst
from vehicle_core.constants import JST, TEAM_LABELS_JA, VEHICLE_ID, Team, agent_name
from vehicle_core.models import AgentRun, Message, MessageRole

from .personas import Persona

log = logging.getLogger(__name__)

MAX_TEXT = 2000
REPLY_TIMEOUT = timedelta(minutes=10)
CLAIM_STALE = timedelta(minutes=2)
CLAIM_CONTAINER = "system"
FAILED_STATUSES = {"failed", "cancelled", "incomplete"}
ASSISTANT_AUTHOR = "agent"  # MCP の post_message と同じ


class ChatBusy(Exception):
    """そのチームのアシスタントが、前の返事を書いている。"""


class ChatFailed(Exception):
    """エージェントに届けられなかった。"""


class AgentChatClient(Protocol):
    def create_conversation(self, team: Team) -> str: ...
    def start_response(self, team: Team, conversation_id: str, prompt: str) -> str: ...
    def get_response(self, team: Team, response_id: str) -> tuple[str, str]: ...


class FoundryChatClient:
    """チームごとのエージェントのエンドポイントに送る（Functions の FoundryResponsesClient と同じ呼び方）。"""

    def __init__(self, project_endpoint: str, credential) -> None:
        self._endpoint = project_endpoint
        self._credential = credential

    @functools.cached_property
    def _project(self):
        from azure.ai.projects import AIProjectClient
        return AIProjectClient(endpoint=self._endpoint, credential=self._credential, allow_preview=True)

    @functools.cache  # noqa: B019 — チームは4つだけ。クライアントの寿命はアプリと同じ
    def _openai(self, team: Team):
        return self._project.get_openai_client(agent_name=agent_name(team))

    def create_conversation(self, team: Team) -> str:
        return self._openai(team).conversations.create().id

    def start_response(self, team: Team, conversation_id: str, prompt: str) -> str:
        return self._openai(team).responses.create(conversation=conversation_id, input=prompt, background=True).id

    def get_response(self, team: Team, response_id: str) -> tuple[str, str]:
        r = self._openai(team).responses.retrieve(response_id)
        return str(r.status), (r.output_text or "")


def chat_prompt(message_id: str, persona: Persona, text: str) -> str:
    return f"チャット（発言 ID: {message_id}）\n{persona.name_ja}（{TEAM_LABELS_JA[persona.team]}、{persona.role}）: {text}"


def run_id_for(message_id: str) -> str:
    return f"run-chat-{message_id}"


def reply_id_for(message_id: str) -> str:
    return f"msg-reply-{message_id}"


def claim_id_for(team: Team) -> str:
    return f"chat-claim-{team.value}"


def _real_now() -> datetime:
    return datetime.now(JST)


class ChatService:
    def __init__(self, store: Store, client: AgentChatClient, now: Callable[[], datetime],
                 system_now: Callable[[], datetime] = _real_now) -> None:
        self.store = store
        self.client = client
        self._now = now
        self._system_now = system_now

    def _running(self, team: Team | None) -> list[dict]:
        where = {"state": "running"} | ({"team": team.value} if team else {})
        return [r for r in self.store.query("agent_runs", where) if (r.get("detail") or {}).get("kind") == "chat"]

    def _fresh_claim(self, team: Team) -> dict | None:
        doc = self.store.get(CLAIM_CONTAINER, claim_id_for(team))
        if doc is None:
            return None
        claimed_at = datetime.fromisoformat(doc["claimed_at"])
        return doc if self._system_now() - claimed_at < CLAIM_STALE else None

    def busy(self, team: Team | None) -> bool:
        """team が None なら、どのチームでも返事待ちがあるか。送っている途中の確保も返事待ちとみなす。"""
        teams = [team] if team else list(Team)
        return bool(self._running(team)) or any(self._fresh_claim(t) for t in teams)

    def _claim(self, team: Team) -> None:
        doc = {"id": claim_id_for(team), "vehicle_id": VEHICLE_ID, "claimed_at": to_jst(self._system_now()).isoformat()}
        for _ in range(2):
            try:
                self.store.create(CLAIM_CONTAINER, doc)
                return
            except Conflict:
                if self._fresh_claim(team) is not None:
                    raise ChatBusy("アシスタントが返事を書いています。少し待ってから送ってください") from None
                try:
                    self.store.delete(CLAIM_CONTAINER, claim_id_for(team))  # 送る途中で止まった古い確保
                except NotFound:
                    pass
        raise ChatBusy("アシスタントが返事を書いています。少し待ってから送ってください")

    def _release(self, team: Team) -> None:
        try:
            self.store.delete(CLAIM_CONTAINER, claim_id_for(team))
        except NotFound:
            pass

    def _conversation(self, team: Team) -> str:
        doc_id = f"ts-{team.value}"
        for _ in range(3):
            doc = self.store.get("team_settings", doc_id)
            if doc and doc.get("chat_conversation_id"):
                return doc["chat_conversation_id"]
            conversation_id = self.client.create_conversation(team)
            if doc is None:
                return conversation_id
            try:
                self.store.replace("team_settings", doc | {"chat_conversation_id": conversation_id}, etag=doc["_etag"])
                return conversation_id
            except (Conflict, NotFound):
                continue  # ほかの読み直しが先に書いた。読み直して、そちらを使う
        raise ChatFailed("チャットの会話を用意できませんでした")

    def _message(self, id_: str, team: Team, role: MessageRole, author: str, text: str, now: datetime) -> None:
        m = Message(id=id_, team=team, role=role, author=author, text=text, created_at=now)
        try:
            self.store.create("messages", m.model_dump(mode="json"))
        except Conflict:
            pass

    def send(self, persona: Persona, text: str) -> str:
        text = text.strip()
        if not text:
            raise ValueError("本文が空です")
        if len(text) > MAX_TEXT:
            raise ValueError(f"本文は {MAX_TEXT} 文字までです")
        team = persona.team
        if self.busy(team):
            raise ChatBusy("アシスタントが返事を書いています。少し待ってから送ってください")
        self._claim(team)
        try:
            if self._running(team):
                raise ChatBusy("アシスタントが返事を書いています。少し待ってから送ってください")
            return self._send_claimed(persona, team, text)
        finally:
            self._release(team)

    def _send_claimed(self, persona: Persona, team: Team, text: str) -> str:
        now = to_jst(self._now())
        message_id = f"msg-{uuid.uuid4().hex[:12]}"
        conversation_id = self._conversation(team)
        self._message(message_id, team, MessageRole.HUMAN, persona.id, text, now)
        try:
            response_id = self.client.start_response(team, conversation_id, chat_prompt(message_id, persona, text))
        except Exception as e:
            log.exception("chat start failed: %s", team)
            self._message(reply_id_for(message_id), team, MessageRole.SYSTEM, "system",
                          "アシスタントに届けられませんでした。もう一度送ってください", now)
            raise ChatFailed("アシスタントに届けられませんでした") from e
        run = AgentRun(id=run_id_for(message_id), team=team, state="running", title="チャットへの返事", started_at=now,
                       detail={"kind": "chat", "conversation_id": conversation_id, "response_id": response_id,
                               "message_id": message_id,
                               "started_real_at": to_jst(self._system_now()).isoformat()})
        self.store.create("agent_runs", run.model_dump(mode="json"))
        return message_id

    def _elapsed(self, run: AgentRun) -> timedelta:
        started = run.detail.get("started_real_at")
        if started:
            return self._system_now() - datetime.fromisoformat(started)
        return to_jst(self._now()) - to_jst(run.started_at)  # 実時間を持たない古い記録

    def sync(self, team: Team | None = None) -> list[str]:
        now = to_jst(self._now())
        closed = []
        for doc in self._running(team):
            run = AgentRun.model_validate(doc)
            detail = run.detail
            try:
                status, text = self.client.get_response(run.team, detail["response_id"])
            except Exception:  # noqa: BLE001 — 1件の失敗で残りを止めない
                log.exception("chat status lookup failed: %s", run.id)
                status, text = "unknown", ""
            if status == "completed":
                role, author, body, extra = MessageRole.ASSISTANT, ASSISTANT_AUTHOR, text or "（返事が空でした）", {}
            elif status in FAILED_STATUSES:
                role, author, body, extra = (MessageRole.SYSTEM, "system", f"返事を作れませんでした（状態: {status}）",
                                             {"error": status})
            elif self._elapsed(run) >= REPLY_TIMEOUT:
                role, author, body, extra = (MessageRole.SYSTEM, "system", "返事を作れませんでした（状態: timeout）",
                                             {"error": "timeout"})
            else:
                continue
            self._message(reply_id_for(detail["message_id"]), run.team, role, author, body, now)
            done = doc | {"state": "done", "finished_at": now.isoformat(), "detail": {**detail, "status": status, **extra}}
            try:
                self.store.replace("agent_runs", done, etag=doc["_etag"])
            except (Conflict, NotFound):
                continue  # ほかの読み直しが先に閉じた
            closed.append(run.id)
        return closed
