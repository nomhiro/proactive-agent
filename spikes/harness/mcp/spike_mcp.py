"""spike 2 用の最小の MCP サーバー（Streamable HTTP、JSON で応答、セッションなし）。

道具は whoami の1つだけ。届いたトークンの中身（ID に関わるクレームとクレーム名の一覧）と、
署名・宛先の検証結果を返す。トークンそのものは返さず、ログにも出さない。
本番では検証に失敗したら拒否する。ここでは中身を見たいので、失敗しても結果として返す。
"""

import json

import jwt
from jwt import PyJWKClient

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
DEFAULT_VERSION = "2025-06-18"
IDENTITY_CLAIMS = ("aud", "iss", "tid", "oid", "sub", "azp", "appid", "azpacr", "appidacr", "idtyp", "ver",
                   "roles", "scp", "xms_par_app_azp", "xms_act_fct", "xms_sub_fct", "xms_idrel")

WHOAMI = {
    "name": "whoami",
    "description": "この MCP サーバーに届いた呼び出し元の ID（トークンのクレーム）を返す。引数はない。",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}


def summarize_claims(claims: dict) -> dict:
    out = {k: claims[k] for k in IDENTITY_CLAIMS if k in claims}
    out["claim_names"] = sorted(claims)
    return out


def inspect_token(authorization: str | None, tenant_id: str, audiences: list[str], headers: dict,
                  jwks_client: PyJWKClient | None = None) -> dict:
    result = {"verified": False, "error": None, "claims": {}, "header_names": sorted(h.lower() for h in headers)}
    if not authorization or not authorization.startswith("Bearer "):
        result["error"] = "Bearer トークンがない"
        return result
    token = authorization.removeprefix("Bearer ").strip()
    try:
        result["claims"] = summarize_claims(jwt.decode(token, options={"verify_signature": False}))
    except jwt.PyJWTError as e:
        result["error"] = f"読めないトークン（{type(e).__name__}）"
        return result
    if jwks_client is None:
        result["error"] = "署名を検証していない（鍵の取得元がない）"
        return result
    try:
        key = jwks_client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=audiences,
                            options={"require": ["exp", "aud", "iss"]})
        if claims.get("tid") != tenant_id:
            result["error"] = "テナントが違う"
        else:
            result["verified"] = True
    except jwt.PyJWTError as e:
        result["error"] = f"検証に失敗（{type(e).__name__}: {e}）"
    return result


def _ok(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle_rpc(msg: dict, identity: dict) -> dict | None:
    if "id" not in msg:  # 通知には返事をしない
        return None
    id_, method, params = msg["id"], msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        requested = params.get("protocolVersion")
        return _ok(id_, {
            "protocolVersion": requested if requested in SUPPORTED_VERSIONS else DEFAULT_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "proactive-spike-mcp", "version": "0.1.0"},
        })
    if method == "ping":
        return _ok(id_, {})
    if method == "tools/list":
        return _ok(id_, {"tools": [WHOAMI]})
    if method == "tools/call":
        if params.get("name") != "whoami":
            return _err(id_, -32602, f"unknown tool: {params.get('name')}")
        return _ok(id_, {"content": [{"type": "text", "text": json.dumps(identity, ensure_ascii=False)}],
                         "isError": False})
    return _err(id_, -32601, f"method not found: {method}")
