from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from vehicle_core.constants import Team
from vehicle_core.models import AgentMail

from proactive_web.app import Deps, create_app
from proactive_web.chat import ChatBusy, ChatFailed, ChatService, chat_prompt
from proactive_web.personas import PERSONAS
from tests.helpers import MORNING, REAL, FixedClock

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
def real():
    return MovingClock(REAL)


@pytest.fixture
def service(store, client, clock, real):
    return ChatService(store, client, clock.now, system_now=real.now)


def test_send_writes_human_message_starts_background_response_and_running_run(store, service, client):
    mid = service.send(PERSONAS["sato"], "今週は v2.1 で手一杯です")
    msg = store.get("messages", mid)
    assert msg["role"] == "human" and msg["author"] == "sato" and msg["text"] == "今週は v2.1 で手一杯です"
    assert msg["team"] == "motor_control" and msg["created_at"] == MORNING.isoformat()
    assert client.prompts == [(Team.MOTOR_CONTROL, "conv-1",
                               f"チャット（発言 ID: {mid}）\n佐藤（モーター制御、モータートルク制御の主担当）: 今週は v2.1 で手一杯です")]
    run = store.get("agent_runs", f"run-chat-{mid}")
    assert run["state"] == "running" and run["team"] == "motor_control"
    assert run["detail"] == {"kind": "chat", "conversation_id": "conv-1", "response_id": "resp-1", "message_id": mid,
                             "started_real_at": REAL.isoformat()}


def test_chat_prompt_format():
    assert chat_prompt("msg-1", PERSONAS["takahashi"], "状況は？") == \
        "チャット（発言 ID: msg-1）\n高橋（車種統括、チーフエンジニア）: 状況は？"


def _mail(id_, frm, to, kind, minutes, **kw):
    return AgentMail(id=id_, thread_id=f"th-{id_}", from_team=frm, to_team=to, kind=kind, body="本文",
                     created_at=MORNING + timedelta(minutes=minutes), **kw).model_dump(mode="json")


def test_chat_prompt_lists_threads_the_team_is_in(store, service, client):
    # チャットの会話は調査の会話と別なので、どの連絡への返答かを書かないとエージェントが結びつけられない
    # （Azure 上での確認 2回目: 佐藤の返答が human_reply にならなかった）
    store.create("agent_mail", _mail("am-1", "integrated_control", "motor_control", "impact_notice", -20,
                                     related_artifact_ids=["SIG-BrkPedalPos", "MDL-MotorTq"]))
    store.create("agent_mail", _mail("am-2", "motor_control", "integrated_control", "human_reply", -10,
                                     stance="cannot"))
    service.send(PERSONAS["sato"], "無理です")
    prompt = client.prompts[-1][2]
    assert "このチームが関わる、エージェント間のスレッド" in prompt
    lines = prompt.splitlines()
    i2 = next(i for i, ln in enumerate(lines) if "am-2" in ln)
    i1 = next(i for i, ln in enumerate(lines) if "am-1" in ln)
    assert i2 < i1  # 新しい順
    assert "th-am-1" in lines[i1] and "integrated_control → motor_control の impact_notice" in lines[i1]
    assert "SIG-BrkPedalPos, MDL-MotorTq" in lines[i1]
    assert "stance cannot" in lines[i2]



def test_chat_prompt_points_to_escalation_after_other_side_said_cannot(store, service, client):
    # Azure 上での確認 5回目: 田中が譲らないと言ったのに、escalation でなく2つ目の下書きを作った
    store.create("agent_mail", _mail("am-1", "integrated_control", "motor_control", "impact_notice", -20))
    store.create("agent_mail", _mail("am-2", "motor_control", "integrated_control", "human_reply", -10,
                                     stance="cannot") | {"thread_id": "th-am-1"})
    service.send(PERSONAS["tanaka"], "周期は戻せません")
    line = next(ln for ln in client.prompts[-1][2].splitlines() if "escalation" in ln)
    assert "th-am-1" in line and "chief_engineer" in line and "下書きは新しく作らない" in line


def test_chat_prompt_has_no_escalation_line_for_the_side_that_said_cannot(store, service, client):
    store.create("agent_mail", _mail("am-1", "integrated_control", "motor_control", "impact_notice", -20))
    store.create("agent_mail", _mail("am-2", "motor_control", "integrated_control", "human_reply", -10,
                                     stance="cannot") | {"thread_id": "th-am-1"})
    service.send(PERSONAS["sato"], "やはり無理です")
    assert "escalation を" not in client.prompts[-1][2]

def test_chat_prompt_leaves_out_other_teams_future_and_analysis_mail(store, service, client):
    store.create("agent_mail", _mail("am-ev", "integrated_control", "evaluation", "impact_notice", -5))
    store.create("agent_mail", _mail("am-later", "integrated_control", "motor_control", "impact_notice", 30))
    store.create("agent_mail", _mail("am-an", "integrated_control", "motor_control", "analysis_request", -5))
    service.send(PERSONAS["sato"], "状況は？")
    prompt = client.prompts[-1][2]
    assert "am-" not in prompt and "スレッド" not in prompt


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


def test_sync_times_out_after_ten_minutes(store, service, client, real):
    mid = service.send(PERSONAS["tanaka"], "a")
    real.value = REAL + timedelta(minutes=9)
    assert service.sync() == []
    real.value = REAL + timedelta(minutes=11)
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


def test_virtual_clock_jump_does_not_time_out_reply(store, service, client, clock):  # 最終レビュー Important 2
    mid = service.send(PERSONAS["tanaka"], "a")
    clock.value = MORNING + timedelta(hours=1)  # シナリオの手順で仮想の時計だけが進む
    assert service.sync() == []
    assert store.get("agent_runs", f"run-chat-{mid}")["state"] == "running"


class ReentrantClient(FakeChatClient):
    """返事を始める途中で、同じチームの別の画面が送る（最終レビュー Important 5）。"""

    def __init__(self) -> None:
        super().__init__()
        self.service = None
        self.inner_error = None

    def start_response(self, team, conversation_id, prompt):
        if self.service is not None:
            other, self.service = self.service, None
            try:
                other.send(PERSONAS["tanaka"], "同時に送った")
            except Exception as e:  # noqa: BLE001
                self.inner_error = e
        return super().start_response(team, conversation_id, prompt)


def test_send_racing_another_send_for_same_team_is_busy(store, clock, real):  # 最終レビュー Important 5
    client = ReentrantClient()
    service = ChatService(store, client, clock.now, system_now=real.now)
    client.service = service
    service.send(PERSONAS["tanaka"], "先に送った")
    assert isinstance(client.inner_error, ChatBusy)
    assert len(client.prompts) == 1
    assert len([r for r in store.query("agent_runs") if r["id"].startswith("run-chat-")]) == 1


def test_claim_is_released_after_send_and_stale_claim_does_not_block(store, service, client, real):
    mid = service.send(PERSONAS["tanaka"], "a")
    assert not [d for d in store.query("system") if d["id"].startswith("chat-claim-")]
    client.finish("completed", "ok")
    service.sync()
    store.create("system", {"id": "chat-claim-integrated_control", "vehicle_id": "kakuu-suv",
                            "claimed_at": (REAL - timedelta(minutes=5)).isoformat()})
    assert service.send(PERSONAS["tanaka"], "b") != mid  # 送る途中で止まった古い確保は無視する
