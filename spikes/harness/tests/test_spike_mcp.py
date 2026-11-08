import json
import sys
from pathlib import Path

import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

from spike_mcp import handle_rpc, inspect_token, summarize_claims  # noqa: E402

IDENTITY = {"verified": False, "error": "no token", "claims": {}, "header_names": []}


def test_initialize_echoes_supported_protocol_version():
    r = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}, IDENTITY)
    assert r["id"] == 1
    assert r["result"]["protocolVersion"] == "2025-06-18"
    assert "tools" in r["result"]["capabilities"]


def test_initialize_falls_back_for_unknown_version():
    r = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
                   IDENTITY)
    assert r["result"]["protocolVersion"] == "2025-06-18"


def test_notification_has_no_response():
    assert handle_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, IDENTITY) is None


def test_tools_list_contains_whoami():
    r = handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, IDENTITY)
    assert [t["name"] for t in r["result"]["tools"]] == ["whoami"]


def test_whoami_returns_identity_as_text():
    r = handle_rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}},
                   IDENTITY)
    assert json.loads(r["result"]["content"][0]["text"]) == IDENTITY


def test_unknown_method_is_error():
    r = handle_rpc({"jsonrpc": "2.0", "id": 4, "method": "nope"}, IDENTITY)
    assert r["error"]["code"] == -32601


def test_summarize_claims_keeps_identity_claims_and_names_only():
    s = summarize_claims({"oid": "o", "azp": "a", "xms_par_app_azp": "bp", "secret_like": "x"})
    assert s["oid"] == "o" and s["azp"] == "a" and s["xms_par_app_azp"] == "bp"
    assert "secret_like" not in s
    assert s["claim_names"] == ["azp", "oid", "secret_like", "xms_par_app_azp"]


def test_inspect_token_without_header():
    r = inspect_token(None, "t", ["aud"], {})
    assert r["verified"] is False and r["claims"] == {}


def test_inspect_token_reports_unverified_claims_when_signature_check_fails():
    token = jwt.encode({"oid": "o", "aud": "aud", "tid": "t"}, "k" * 32, algorithm="HS256")
    r = inspect_token(f"Bearer {token}", "t", ["aud"], {"X-Test": "1"}, jwks_client=None)
    assert r["verified"] is False
    assert r["claims"]["oid"] == "o"
    assert r["header_names"] == ["x-test"]
