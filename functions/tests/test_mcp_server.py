import json
from datetime import datetime

import pytest
from vehicle_core.constants import JST, Team
from vehicle_core.models import TeamSettings

from proactive_functions.mcp import protocol
from proactive_functions.mcp.context import ToolContext
from proactive_functions.mcp.protocol import Registry, Tool
from proactive_functions.mcp.server import build_registry, handle_mcp_http
from tests.fakes import FakeVerifier, MemoryStore

NIGHT = datetime(2026, 11, 17, 21, 10, tzinfo=JST)
DAY = datetime(2026, 11, 18, 10, 0, tzinfo=JST)


class CountingRegistry(Registry):
    def __init__(self):
        super().__init__()
        self.calls = []

        def who(ctx, args):
            self.calls.append(ctx.team)
            return {"team": ctx.team.value}
        self.add(Tool(name="who", description="呼び出し元のチーム", input_schema={"type": "object", "properties": {}},
                      handler=who))


def store_with_mapping():
    store = MemoryStore()
    store.create("team_settings", TeamSettings(id="ts-integrated_control", team=Team.INTEGRATED_CONTROL,
                                               agent_client_id="c-ic").model_dump(mode="json"))
    return store


def post(body, authorization="Bearer c-ic", *, registry=None, store=None, now=NIGHT, method="POST"):
    store = store or store_with_mapping()
    registry = registry or CountingRegistry()
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    res = handle_mcp_http(method, authorization, raw, verifier=FakeVerifier(), store=store, registry=registry,
                          make_ctx=lambda team: ToolContext(team=team, store=store, now=now))
    return res, registry


CALL = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "who", "arguments": {}}}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def test_http_rejects_tools_call_without_token():
    res, reg = post(CALL, authorization=None)
    assert res.status == 401 and reg.calls == []


@pytest.mark.parametrize("required,status", [(True, 401), (False, 200)])
def test_http_discovery_without_token_follows_setting(monkeypatch, required, status):
    monkeypatch.setattr(protocol, "DISCOVERY_REQUIRES_TOKEN", required)
    res, _ = post(LIST, authorization=None)
    assert res.status == status
    if status == 200:
        assert [t["name"] for t in res.body["result"]["tools"]] == ["who"]


def test_discovery_requires_token_by_default():
    # spike で、Foundry は探索のメソッドにもトークンを付けると確かめた（Plan 3 決定 2）
    assert protocol.DISCOVERY_REQUIRES_TOKEN is True


def test_http_rejects_invalid_token_even_on_discovery():
    res, _ = post(LIST, authorization="Basic xyz")
    assert res.status == 401


def test_http_rejects_unmapped_client_with_403():
    res, reg = post(CALL, authorization="Bearer someone-else")
    assert res.status == 403 and reg.calls == []


def test_http_rejects_non_post_with_405():
    assert post(LIST, method="GET")[0].status == 405


def test_http_non_json_body_is_parse_error():
    res, _ = post(b"not json")
    assert res.status == 200 and res.body["error"]["code"] == -32700


def test_http_notification_only_returns_202():
    res, _ = post(INITIALIZED)
    assert res.status == 202 and res.body is None


def test_http_batch_returns_list_of_replies():
    res, _ = post([LIST, INITIALIZED, CALL])
    assert res.status == 200 and [r["id"] for r in res.body] == [2, 1]


def test_http_passes_caller_team_to_tools():
    res, reg = post(CALL)
    assert reg.calls == [Team.INTEGRATED_CONTROL]
    assert json.loads(res.body["result"]["content"][0]["text"]) == {"team": "integrated_control"}


def call_get_now(now):
    res, _ = post({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "get_now", "arguments": {}}},
                  registry=build_registry(), now=now)
    return json.loads(res.body["result"]["content"][0]["text"])


def test_get_now_uses_virtual_clock_and_quiet_hours():
    assert call_get_now(NIGHT) == {"now": "2026-11-17T21:10:00+09:00", "date": "2026-11-17", "in_quiet_hours": True}
    assert call_get_now(DAY)["in_quiet_hours"] is False


def test_http_deeply_nested_json_is_parse_error_not_500():  # 最終レビューの I2
    res, reg = post(b"[" * 200_000)
    assert res.status == 200 and res.body["error"]["code"] == -32700 and reg.calls == []


def test_http_without_token_is_rejected_before_reading_body():  # 最終レビューの I2
    made = []
    res = handle_mcp_http("POST", None, b"[" * 200_000, verifier=FakeVerifier(), store=store_with_mapping(),
                          registry=CountingRegistry(), make_ctx=lambda team: made.append(team))
    assert res.status == 401 and made == []


def test_http_empty_batch_is_invalid_request():  # 最終レビューの M8
    res, reg = post([])
    assert res.status == 200 and res.body["error"]["code"] == -32600 and reg.calls == []
