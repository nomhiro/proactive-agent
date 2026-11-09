from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from vehicle_core.constants import Team

from proactive_web.app import Deps, create_app
from proactive_web.chat import ChatBusy, ChatFailed, ChatService, chat_prompt
from proactive_web.personas import PERSONAS
from tests.helpers import MORNING, FixedClock

USER = {"X-MS-CLIENT-PRINCIPAL-NAME": "someone@example.com"}


class FakeChatClient:
    def __init__(self, fail_start: bool = False) -> None:
        self.prompts: list[tuple[Team, str, str]] = []
        self.conversations_created = 0
        self.status: dict[str, tuple[str, str]] = {}
        self.fail_start = fail_start
        self.lookups: list[str] = []

    def create_conversation(self, team: Team) -> str:
        self.conversations_created += 1
        return f"conv-{self.conversations_created}"

    def start_response(self, team: Team, conversation_id: str, prompt: str) -> str:
        if self.fail_start:
            raise RuntimeError("foundry unavailable")
        self.prompts.append((team, conversation_id, prompt))
        rid = f"resp-{len(self.prompts)}"
        self.status[rid] = ("in_progress", "")
        return rid

    def get_response(self, team: Team, response_id: str) -> tuple[str, str]:
        self.lookups.append(response_id)
        return self.status[response_id]

    def finish(self, status: str, text: str = "", rid: str | None = None) -> None:
        self.status[rid or f"resp-{len(self.prompts)}"] = (status, text)


class MovingClock:
    def __init__(self, now) -> None:
        self.value = now

    def now(self):
        return self.value


@pytest.fixture
def client():
    return FakeChatClient()


@pytest.fixture
def clock():
    return MovingClock(MORNING)


@pytest.fixture
def service(store, client, clock):
    return ChatService(store, client, clock.now)


def test_send_writes_human_message_starts_background_response_and_running_run(store, service, client):
    mid = service.send(PERSONAS["sato"], "今週は v2.1 で手一杯です")
    msg = store.get("messages", mid)
    assert msg["role"] == "human" and msg["author"] == "sato" and msg["text"] == "今週は v2.1 で手一杯です"
    assert msg["team"] == "motor_control" and msg["created_at"] == MORNING.isoformat()
    assert client.prompts == [(Team.MOTOR_CONTROL, "conv-1",
                               f"チャット（発言 ID: {mid}）\n佐藤（モーター制御、モータートルク制御の主担当）: 今週は v2.1 で手一杯です")]
    run = store.get("agent_runs", f"run-chat-{mid}")
    assert run["state"] == "running" and run["team"] == "motor_control"
    assert run["detail"] == {"kind": "chat", "conversation_id": "conv-1", "response_id": "resp-1", "message_id": mid}


def test_chat_prompt_format():
    assert chat_prompt("msg-1", PERSONAS["takahashi"], "状況は？") == \
        "チャット（発言 ID: msg-1）\n高橋（車種統括、チーフエンジニア）: 状況は？"


def test_conversation_is_created_once_per_team_and_saved(store, service, client):
    service.send(PERSONAS["tanaka"], "a")
    client.finish("completed", "ok")
    service.sync()
    service.send(PERSONAS["tanaka"], "b")
    assert client.conversations_created == 1
    assert [p[1] for p in client.prompts] == ["conv-1", "conv-1"]
    assert store.get("team_settings", "ts-integrated_control")["chat_conversation_id"] == "conv-1"


def test_send_while_reply_running_is_busy_and_starts_nothing(store, service, client):  # Review Focus 3
    service.send(PERSONAS["tanaka"], "a")
    assert service.busy(Team.INTEGRATED_CONTROL) and not service.busy(Team.MOTOR_CONTROL)
    with pytest.raises(ChatBusy):
        service.send(PERSONAS["tanaka"], "b")
    assert len(client.prompts) == 1
    assert len(store.query("messages", {"team": "integrated_control"})) == 1


def test_sync_writes_reply_and_closes_run_once(store, service, client):
    mid = service.send(PERSONAS["tanaka"], "a")
    client.finish("completed", "返事です")
    assert service.sync() == [f"run-chat-{mid}"]
    reply = store.get("messages", f"msg-reply-{mid}")
    assert reply["role"] == "assistant" and reply["author"] == "agent" and reply["text"] == "返事です"
    assert reply["team"] == "integrated_control"
    run = store.get("agent_runs", f"run-chat-{mid}")
    assert run["state"] == "done" and run["finished_at"] == MORNING.isoformat()
    assert service.sync() == []
    assert not service.busy(Team.INTEGRATED_CONTROL)


def test_sync_writes_system_message_on_failure(store, service, client):
    mid = service.send(PERSONAS["tanaka"], "a")
    client.finish("failed")
    service.sync()
    reply = store.get("messages", f"msg-reply-{mid}")
    assert reply["role"] == "system" and reply["text"] == "返事を作れませんでした（状態: failed）"
    assert store.get("agent_runs", f"run-chat-{mid}")["detail"]["error"] == "failed"


def test_sync_times_out_after_ten_minutes(store, service, client, clock):
    mid = service.send(PERSONAS["tanaka"], "a")
    clock.value = MORNING + timedelta(minutes=9)
    assert service.sync() == []
    clock.value = MORNING + timedelta(minutes=11)
    assert service.sync() == [f"run-chat-{mid}"]
    assert store.get("messages", f"msg-reply-{mid}")["text"] == "返事を作れませんでした（状態: timeout）"


def test_sync_leaves_in_progress_run_open_and_filters_by_team(store, service, client):
    service.send(PERSONAS["tanaka"], "a")
    assert service.sync() == []
    client.finish("completed", "x")
    assert service.sync(Team.MOTOR_CONTROL) == []
    assert len(service.sync(Team.INTEGRATED_CONTROL)) == 1


def test_sync_skips_lookup_errors(store, service, client):
    service.send(PERSONAS["tanaka"], "a")
    client.status.clear()  # 状態が読めない
    assert service.sync() == []


def test_empty_or_too_long_text_is_rejected(store, service, client):
    for text in ["  ", "あ" * 2001]:
        with pytest.raises(ValueError):
            service.send(PERSONAS["tanaka"], text)
    assert client.prompts == [] and store.query("messages") == []


def test_start_failure_raises_chat_failed_and_leaves_no_running_run(store, client):
    failing = FakeChatClient(fail_start=True)
    service = ChatService(store, failing, lambda: MORNING)
    with pytest.raises(ChatFailed):
        service.send(PERSONAS["tanaka"], "a")
    assert not service.busy(Team.INTEGRATED_CONTROL)


def test_chat_routes(store, client):
    service = ChatService(store, client, lambda: MORNING)
    c = TestClient(create_app(Deps(store=store, clock=FixedClock(MORNING), chat=service)))
    r = c.post("/api/chat", json={"persona": "tanaka", "text": "状況は？"}, headers=USER)
    assert r.status_code == 200 and r.json()["message_id"].startswith("msg-")
    assert c.post("/api/chat", json={"persona": "tanaka", "text": "もう一度"}, headers=USER).status_code == 409
    assert c.get("/api/state", params={"persona": "tanaka"}, headers=USER).json()["chat_busy"] is True
    client.finish("completed", "返事")
    state = c.get("/api/state", params={"persona": "tanaka"}, headers=USER).json()
    assert state["chat_busy"] is False and state["messages"][-1]["text"] == "返事"
    assert c.post("/api/chat", json={"persona": "sato", "text": " "}, headers=USER).status_code == 422
