"""spike 用の関数: MCP サーバー（spike 2）と、キューを受けてエージェントを起動する関数（spike 6）。"""

import functools
import json
import logging
import os

import azure.functions as func

from spike_mcp import handle_rpc, inspect_token

app = func.FunctionApp()


@functools.cache
def _jwks():
    from jwt import PyJWKClient
    return PyJWKClient(f"https://login.microsoftonline.com/{os.environ['MCP_TENANT_ID']}/discovery/v2.0/keys",
                       cache_keys=True)


def _json(body, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body, ensure_ascii=False), status_code=status, mimetype="application/json")


@app.route(route="mcp", methods=["GET", "POST", "DELETE"], auth_level=func.AuthLevel.ANONYMOUS)
def mcp(req: func.HttpRequest) -> func.HttpResponse:
    if req.method != "POST":  # SSE の待ち受けとセッションの削除は使わない
        return func.HttpResponse(status_code=405)
    identity = inspect_token(req.headers.get("Authorization"), os.environ["MCP_TENANT_ID"],
                             [a.strip() for a in os.environ["MCP_AUDIENCES"].split(",")], dict(req.headers),
                             jwks_client=_jwks())
    try:
        msg = req.get_json()
    except ValueError:
        return _json({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}, 400)
    logging.info("spike-mcp method=%s identity=%s", msg.get("method") if isinstance(msg, dict) else "batch",
                 json.dumps(identity, ensure_ascii=False))
    if isinstance(msg, list):
        replies = [r for m in msg if (r := handle_rpc(m, identity)) is not None]
        return _json(replies) if replies else func.HttpResponse(status_code=202)
    reply = handle_rpc(msg, identity)
    return func.HttpResponse(status_code=202) if reply is None else _json(reply)


@app.queue_trigger(arg_name="msg", queue_name="probe", connection="AzureWebJobsStorage")
def probe(msg: func.QueueMessage) -> None:
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    from spike_invoke import run_probe

    req = json.loads(msg.get_body().decode("utf-8"))
    credential = DefaultAzureCredential()
    result = run_probe(os.environ["FOUNDRY_PROJECT_ENDPOINT"], req["agent"], req["prompt"], req.get("mode", "sync"),
                       credential)
    result["caller"] = "functions-managed-identity"
    logging.info("spike-probe %s", json.dumps(result, ensure_ascii=False)[:4000])
    blobs = BlobServiceClient(os.environ["PROBE_BLOB_ENDPOINT"], credential=credential)
    blobs.get_blob_client("probe-results", f"{req['id']}.json").upload_blob(
        json.dumps(result, ensure_ascii=False, indent=2), overwrite=True)
