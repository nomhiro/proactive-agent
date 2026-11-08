import json
from datetime import datetime

from vehicle_core.constants import JST, Team

from proactive_functions.mcp.context import ToolContext, ToolError
from proactive_functions.mcp.protocol import Registry, Tool, handle_rpc
from tests.fakes import MemoryStore

NOW = datetime(2026, 11, 17, 21, 10, tzinfo=JST)


def make_registry() -> Registry:
    reg = Registry()
    reg.add(Tool(name="echo", description="引数をそのまま返す",
                 input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                 handler=lambda ctx, args: {"text": args["text"], "team": ctx.team.value}))

    def deny(ctx, args):
        raise ToolError("ほかのチームの文書は書けません")
    reg.add(Tool(name="deny", description="いつも拒否する", input_schema={"type": "object", "properties": {}},
                 handler=deny))

    def boom(ctx, args):
        raise RuntimeError("secret detail")
    reg.add(Tool(name="boom", description="内部で失敗する", input_schema={"type": "object", "properties": {}},
                 handler=boom))
    return reg


CTX = ToolContext(team=Team.INTEGRATED_CONTROL, store=MemoryStore(), now=NOW)


def rpc(method, params=None, id_=1):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return handle_rpc(msg, make_registry(), CTX)


def call(name, arguments=None):
    return rpc("tools/call", {"name": name, "arguments": arguments or {}})


def test_initialize_negotiates_known_version():
    assert rpc("initialize", {"protocolVersion": "2025-03-26"})["result"]["protocolVersion"] == "2025-03-26"


def test_initialize_falls_back_to_default_version():
    res = rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]
    assert res["protocolVersion"] == "2025-06-18"
    assert res["capabilities"] == {"tools": {"listChanged": False}}


def test_notification_returns_none():
    assert handle_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, make_registry(), CTX) is None


def test_ping_returns_empty_result():
    assert rpc("ping")["result"] == {}


def test_tools_list_returns_registered_tools():
    tools = {t["name"]: t for t in rpc("tools/list")["result"]["tools"]}
    assert set(tools) == {"echo", "deny", "boom"}
    assert tools["echo"]["description"] == "引数をそのまま返す"
    assert tools["echo"]["inputSchema"]["required"] == ["text"]


def test_unknown_method_is_jsonrpc_error():
    # Foundry は server/discover も送ってくる（spike で確認）。知らないメソッドとして返せば先へ進む
    assert rpc("server/discover")["error"]["code"] == -32601


def test_unknown_tool_is_invalid_params():
    assert call("nope")["error"]["code"] == -32602


def test_tool_result_is_json_text_with_caller_team():
    res = call("echo", {"text": "こんにちは"})["result"]
    assert res["isError"] is False
    assert json.loads(res["content"][0]["text"]) == {"text": "こんにちは", "team": "integrated_control"}


def test_tool_error_becomes_is_error_result():
    res = call("deny")["result"]
    assert res["isError"] is True and "ほかのチーム" in res["content"][0]["text"]


def test_missing_required_argument_is_is_error_result():
    res = call("echo", {})["result"]
    assert res["isError"] is True and "text" in res["content"][0]["text"]


def test_non_object_arguments_is_invalid_params():
    assert rpc("tools/call", {"name": "echo", "arguments": "text"})["error"]["code"] == -32602


def test_unexpected_exception_is_is_error_without_details():
    res = call("boom")["result"]
    assert res["isError"] is True and "secret detail" not in res["content"][0]["text"]


def test_non_object_message_is_invalid_request():
    assert handle_rpc("hello", make_registry(), CTX)["error"]["code"] == -32600
