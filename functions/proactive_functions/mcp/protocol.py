"""MCP の JSON-RPC（状態を持たない Streamable HTTP、JSON で応答）と、道具の登録簿。

- 道具の中の拒否と入力の誤りは、tools/call の結果に isError: true で返す（LLM が読んで直せるように）
- 知らないメソッド・知らない道具・形の壊れた要求は、JSON-RPC のエラーで返す
- どの場合も例外を外に出さない（HTTP 500 にしない）
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .context import ToolContext, ToolError

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26")
DEFAULT_VERSION = "2025-06-18"
# 探索のメソッド（initialize、tools/list など）にもトークンを求めるか。
# spike で、Foundry はすべてのメソッドにトークンを付けると確かめた（Plan 3 決定 2）
DISCOVERY_REQUIRES_TOKEN = True
SERVER_INFO = {"name": "proactive-agent-mcp", "version": "1.0.0"}

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[ToolContext, dict], Any]


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"道具の名前が重複しています: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[dict]:
        return [{"name": t.name, "description": t.description, "inputSchema": t.input_schema}
                for t in self._tools.values()]


def _ok(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _text_result(payload: Any, *, is_error: bool) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call_tool(id_, params: dict, registry: Registry, ctx: ToolContext | None) -> dict:
    name = params.get("name")
    tool = registry.get(name) if isinstance(name, str) else None
    if tool is None:
        return _err(id_, -32602, f"知らない道具です: {name}")
    args = params.get("arguments", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return _err(id_, -32602, "arguments はオブジェクトで渡してください")
    if ctx is None:  # トークンなしで道具を呼ぶ経路は HTTP の層で止めている
        return _err(id_, -32603, "呼び出し元のチームがわかりません")
    missing = [k for k in tool.input_schema.get("required", []) if k not in args]
    if missing:
        return _ok(id_, _text_result(f"必須の引数がありません: {', '.join(missing)}", is_error=True))
    try:
        result = tool.handler(ctx, args)
    except ToolError as e:
        return _ok(id_, _text_result(e.reason, is_error=True))
    except ValidationError as e:
        return _ok(id_, _text_result(f"引数の形が正しくありません（{e.error_count()} 件の誤り）", is_error=True))
    except Exception:  # noqa: BLE001 — 中身はログにだけ残し、エージェントには返さない
        log.exception("mcp tool failed: team=%s tool=%s", ctx.team, name)
        return _ok(id_, _text_result("道具の内部でエラーが起きました。少し待ってからやり直してください", is_error=True))
    return _ok(id_, _text_result(result, is_error=False))


def handle_rpc(msg: Any, registry: Registry, ctx: ToolContext | None) -> dict | None:
    if not isinstance(msg, dict):
        return _err(None, -32600, "要求の形が正しくありません")
    if "id" not in msg:  # 通知には返事をしない
        return None
    id_, method = msg["id"], msg.get("method")
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        return _err(id_, -32602, "params はオブジェクトで渡してください")
    if method == "initialize":
        requested = params.get("protocolVersion")
        return _ok(id_, {
            "protocolVersion": requested if requested in SUPPORTED_VERSIONS else DEFAULT_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })
    if method == "ping":
        return _ok(id_, {})
    if method == "tools/list":
        return _ok(id_, {"tools": registry.list()})
    if method == "tools/call":
        return _call_tool(id_, params, registry, ctx)
    return _err(id_, -32601, f"知らないメソッドです: {method}")


def needs_token(msg: Any) -> bool:
    """この要求にトークンが要るか。道具の呼び出しはいつも要る。"""
    if isinstance(msg, dict) and msg.get("method") == "tools/call":
        return True
    return DISCOVERY_REQUIRES_TOKEN
