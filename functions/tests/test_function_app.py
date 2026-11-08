import importlib
import json

from proactive_functions.settings import load_settings


def test_health_returns_vehicle_id():
    import function_app
    resp = function_app._health()
    assert resp.status_code == 200
    assert json.loads(resp.get_body()) == {"ok": True, "vehicle_id": "kakuu-suv"}


def test_all_functions_registered_without_touching_azure(monkeypatch):
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)  # import だけでは設定を読まない
    import function_app
    importlib.reload(function_app)
    names = {f.get_function_name() for f in function_app.app.get_functions()}
    assert names == {"health", "agent_write", "route_change_events", "route_test_runs", "deliver_agent_mail",
                     "tick_on_clock", "tick_timer", "publish_messages", "publish_proposals", "publish_agent_runs",
                     "publish_notifications", "publish_watches"}


def test_load_settings_reads_audiences_list():
    s = load_settings({"COSMOS_ENDPOINT": "https://c", "COSMOS_DATABASE": "proactive", "WEBPUBSUB_ENDPOINT": "https://w",
                       "WEBPUBSUB_HUB": "proactive", "GATEWAY_TENANT_ID": "t", "GATEWAY_AUDIENCES": "a, api://t/b",
                       "AGENT_INVOKER": "log"})
    assert s.gateway_audiences == ["a", "api://t/b"]
    assert s.agent_invoker == "log"



def test_change_feed_functions_have_retry_policy():  # 最終レビューの指摘1: 例外でバッチを失わない
    import function_app
    importlib.reload(function_app)
    cosmos = [f for f in function_app.app.get_functions() if f.get_trigger().get_binding_name() == "cosmosDBTrigger"]
    assert len(cosmos) == 9
    for f in cosmos:
        policy = f.get_settings_dict("retry_policy")
        assert policy and policy["strategy"] == "exponential_backoff", f.get_function_name()
