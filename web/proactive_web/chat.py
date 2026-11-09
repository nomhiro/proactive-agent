"""チャット（決定 3〜6、設計書 7.8 節）。

- 会話はチームに1本（team_settings.chat_conversation_id）。なければ最初のチャットで作る
- 人の発言を messages に書き、決まった形のプロンプトを background=True で送り、作業記録 run-chat-<発言 ID> を作って戻る
- 返事の受け取りは sync。画面の読み直し（/api/state）と CLI が呼ぶ。裏で待ち続ける処理は持たない
- 返事待ちのあいだは、そのチームの新しいチャットを受け付けない（ChatBusy）
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
from vehicle_core.constants import TEAM_LABELS_JA, Team, agent_name
from vehicle_core.models import AgentRun, Message, MessageRole

from .personas import Persona

log = logging.getLogger(__name__)

MAX_TEXT = 2000
REPLY_TIMEOUT = timedelta(minutes=10)
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


class ChatService:
    def __init__(self, store: Store, client: AgentChatClient, now: Callable[[], datetime]) -> None:
        self.store = store
        self.client = client
        self._now = now

    def _running(self, team: Team | None) -> list[dict]:
        where = {"state": "running"} | ({"team": team.value} if team else {})
        return [r for r in self.store.query("agent_runs", where) if (r.get("detail") or {}).get("kind") == "chat"]

    def busy(self, team: Team | None) -> bool:
        """team が None なら、どのチームでも返事待ちがあるか。"""
        return bool(self._running(team))

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
                               "message_id": message_id})
        self.store.create("agent_runs", run.model_dump(mode="json"))
        return message_id

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
            elif now - to_jst(run.started_at) >= REPLY_TIMEOUT:
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
