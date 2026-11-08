"""MCP サーバーの HTTP の入り口と、道具の登録簿の組み立て。

認証の順序（Plan 3 決定 2）:
1. トークンが付いていれば、本文を処理する前に検証する。不正なら 401、対応表にない client ID なら 403
2. トークンがなければ、道具の呼び出しは 401。探索のメソッドは DISCOVERY_REQUIRES_TOKEN に従う
どの拒否でも、道具は1つも動かさない。トークンはログに出さない。
"""

import json
import logging
from collections.abc import Callable

from pydantic import BaseModel
from vehicle_core.constants import Team
from vehicle_core.models import TeamSettings
from vehicle_core.notify_policy import is_quiet

from ..agent_writes import team_for_client
from ..auth import AuthError, TokenVerifier
from . import protocol
from .context import ToolContext
from .protocol import Registry, Tool, handle_rpc
from .read_tools import register_read_tools
from .write_tools import register_write_tools

log = logging.getLogger(__name__)


class McpHttpResult(BaseModel):
    status: int
    body: dict | list | None = None


def _team_settings(ctx: ToolContext) -> TeamSettings:
    found = ctx.store.query("team_settings", {"team": ctx.team.value})
    return TeamSettings.model_validate(found[0]) if found else TeamSettings(id=f"ts-{ctx.team.value}", team=ctx.team)


def _get_now(ctx: ToolContext, args: dict) -> dict:
    return {"now": ctx.now.isoformat(), "date": ctx.now.date().isoformat(),
            "in_quiet_hours": is_quiet(ctx.now, _team_settings(ctx))}


def build_registry() -> Registry:
    reg = Registry()
    reg.add(Tool(
        name="get_now",
        description="現在の日時（日本時間、デモの仮想の時計）を返す。日付や曜日、期限までの日数を考えるときは、"
                    "作業環境の時計ではなく必ずこれを使う。in_quiet_hours はチームの静かな時間帯かどうか。",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_get_now,
    ))
    register_read_tools(reg)
    register_write_tools(reg)
    return reg


def handle_mcp_http(
    method: str,
    authorization: str | None,
    body: bytes,
    *,
    verifier: TokenVerifier,
    store,
    registry: Registry,
    make_ctx: Callable[[Team], ToolContext],
) -> McpHttpResult:
    if method.upper() != "POST":  # SSE の待ち受けとセッションの削除は使わない
        return McpHttpResult(status=405)

    team: Team | None = None
    if authorization:
        try:
            client_id = verifier.verify(authorization)
        except AuthError as e:
            return McpHttpResult(status=401, body={"reason": e.reason})
        found = team_for_client(store, client_id)
        if found is None:
            log.warning("mcp: unmapped client")
            return McpHttpResult(status=403, body={"reason": "このエージェントは登録されていません"})
        team = Team(found)

    try:
        msg = json.loads(body or b"null")
    except (ValueError, UnicodeDecodeError):
        return McpHttpResult(status=200, body=protocol._err(None, -32700, "本文が JSON ではありません"))

    messages = msg if isinstance(msg, list) else [msg]
    if team is None and any(protocol.needs_token(m) for m in messages):
        return McpHttpResult(status=401, body={"reason": "Bearer トークンがありません"})

    ctx = make_ctx(team) if team is not None else None
    for m in messages:
        if isinstance(m, dict) and m.get("method") == "tools/call":
            log.info("mcp tools/call: team=%s tool=%s", team, (m.get("params") or {}).get("name"))
    replies = [r for m in messages if (r := handle_rpc(m, registry, ctx)) is not None]
    if not replies:
        return McpHttpResult(status=202)
    return McpHttpResult(status=200, body=replies if isinstance(msg, list) else replies[0])
