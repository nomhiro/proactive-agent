"""Azure Functions のトリガー定義。どの関数も、本体（proactive_functions）を呼ぶだけにする。

依存（Cosmos、仮想時計、Web PubSub など）は最初の呼び出しで1度だけ作る。
import しただけでは Azure にも設定にも触れない（テストで関数の登録を確かめられるように）。
"""

import functools
import json
from types import SimpleNamespace

import azure.functions as func
from vehicle_core.constants import VEHICLE_ID

from proactive_functions.handlers import handle_agent_mail, handle_change_events, handle_test_runs
from proactive_functions.publisher import PUBLISHED_CONTAINERS, publish_changes

app = func.FunctionApp()

COSMOS = dict(connection="COSMOS", database_name="%COSMOS_DATABASE%", lease_container_name="leases",
              create_lease_container_if_not_exists=False)
# Cosmos のトリガーは、既定では例外の出たバッチを再試行せずに読み飛ばす（そのバッチは失われる）。
# 処理はどれも冪等なので、一時的な失敗は再試行で取り戻す
RETRY = dict(strategy="exponential_backoff", max_retry_count="5", minimum_interval="00:00:05",
             maximum_interval="00:05:00")


@functools.cache
def _deps() -> SimpleNamespace:
    from azure.identity import DefaultAzureCredential

    from proactive_functions.auth import EntraTokenVerifier
    from proactive_functions.clock import StoredClock
    from proactive_functions.investigations import LoggingInvoker
    from proactive_functions.mcp.server import build_registry
    from proactive_functions.publisher import WebPubSubPublisher
    from proactive_functions.settings import load_settings
    from proactive_functions.store import CosmosStore

    s = load_settings()
    credential = DefaultAzureCredential()
    store = CosmosStore(s.cosmos_endpoint, s.cosmos_database, credential)
    return SimpleNamespace(
        store=store,
        clock=StoredClock(store),
        invoker=LoggingInvoker(),
        publisher=WebPubSubPublisher(s.webpubsub_endpoint, s.webpubsub_hub, credential),
        verifier=EntraTokenVerifier(s.gateway_tenant_id, s.gateway_audiences),
        registry=build_registry(),
    )


def _docs(docs: func.DocumentList) -> list[dict]:
    return [json.loads(d.to_json()) for d in docs]


def _tick() -> None:
    from proactive_functions.tick import run_tick
    d = _deps()
    run_tick(d.store, d.invoker, d.publisher, d.clock.now())


# --- HTTP ---------------------------------------------------------------

def _health() -> func.HttpResponse:
    body = {"ok": True, "vehicle_id": VEHICLE_ID}
    return func.HttpResponse(json.dumps(body), status_code=200, mimetype="application/json")


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _health()


@app.route(route="mcp", methods=["GET", "POST", "DELETE"], auth_level=func.AuthLevel.ANONYMOUS)
def mcp(req: func.HttpRequest) -> func.HttpResponse:
    from proactive_functions.mcp.context import ToolContext
    from proactive_functions.mcp.server import handle_mcp_http
    d = _deps()
    now = d.clock.now()
    result = handle_mcp_http(
        req.method, req.headers.get("Authorization"), req.get_body(),
        verifier=d.verifier, store=d.store, registry=d.registry,
        make_ctx=lambda team: ToolContext(team=team, store=d.store, now=now),
    )
    body = json.dumps(result.body, ensure_ascii=False) if result.body is not None else None
    return func.HttpResponse(body, status_code=result.status, mimetype="application/json")


# --- 変更フィード ---------------------------------------------------------

@app.retry(**RETRY)
@app.cosmos_db_trigger(arg_name="docs", container_name="change_events", lease_container_prefix="route-ce-", **COSMOS)
def route_change_events(docs: func.DocumentList) -> None:
    handle_change_events(_docs(docs), _deps().store)


@app.retry(**RETRY)
@app.cosmos_db_trigger(arg_name="docs", container_name="test_runs", lease_container_prefix="route-tr-", **COSMOS)
def route_test_runs(docs: func.DocumentList) -> None:
    handle_test_runs(_docs(docs), _deps().store)


@app.retry(**RETRY)
@app.cosmos_db_trigger(arg_name="docs", container_name="agent_mail", lease_container_prefix="mail-", **COSMOS)
def deliver_agent_mail(docs: func.DocumentList) -> None:
    handle_agent_mail(_docs(docs), _deps().store)


@app.retry(**RETRY)
@app.cosmos_db_trigger(arg_name="docs", container_name="system", lease_container_prefix="tick-", **COSMOS)
def tick_on_clock(docs: func.DocumentList) -> None:
    _tick()


def _register_publisher(container: str) -> None:
    def publish(docs: func.DocumentList) -> None:
        d = _deps()
        publish_changes(container, _docs(docs), d.store, d.publisher)

    name = f"publish_{container}"
    publish.__name__ = publish.__qualname__ = name
    trigger = app.cosmos_db_trigger(arg_name="docs", container_name=container,
                                    lease_container_prefix=f"pub-{container}-", **COSMOS)
    app.function_name(name=name)(app.retry(**RETRY)(trigger(publish)))


for _container in PUBLISHED_CONTAINERS:
    _register_publisher(_container)


# --- タイマー ------------------------------------------------------------

@app.timer_trigger(arg_name="timer", schedule="0 */1 * * * *", run_on_startup=False)
def tick_timer(timer: func.TimerRequest) -> None:
    _tick()
