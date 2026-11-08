"""確認 7: Routines を cron `0 8 * * *`、`Asia/Tokyo` で作り、手動起動（自分の ID と Functions の ID）できるか。

harness は会話なしの要求を受け付けないので、会話を指定しない Routine（A）と、
先に作った会話を指定する Routine（B）の両方を試す。エージェントの仕事が本当に動いたかは、
MCP サーバーの記録（probe-results/mcp-log/）に whoami の呼び出しが増えたかで見る。
"""

import json
import time

from _env import azd_env, project_client, queue_probe, save
from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient

AGENT = "spike-a"
PROMPT = "whoami ツールを1回呼び、結果の azp だけを返してください。"
TERMINAL = {"succeeded", "completed", "failed", "cancelled", "canceled", "error"}


def _as_dict(x):
    return x.as_dict() if hasattr(x, "as_dict") else (x if isinstance(x, dict) else str(x))


def _tool_calls(container: ContainerClient) -> int:
    n = 0
    for b in container.list_blobs(name_starts_with="mcp-log/"):
        if b.name.endswith("tools_call.json"):
            n += 1
    return n


def _wait_runs(routines, name: str, count: int, timeout_s: int = 420) -> list:
    deadline = time.monotonic() + timeout_s
    runs = []
    while time.monotonic() < deadline:
        runs = [_as_dict(r) for r in routines.list_runs(name)]
        done = [r for r in runs if str(r.get("phase", "")).lower() in TERMINAL]
        if len(done) >= count:
            return runs
        time.sleep(15)
    return runs


def _try(name: str, routines, env, container, conversation: str | None) -> dict:
    out: dict = {"routine": name, "conversation": conversation}
    action = {"type": "invoke_agent_responses_api", "agent_name": AGENT, "input": PROMPT}
    if conversation:
        action["conversation"] = conversation
    try:
        created = routines.create_or_update(
            routine_name=name, description="spike（確認 7）", enabled=True,
            triggers={"morning": {"type": "schedule", "cron_expression": "0 8 * * *", "time_zone": "Asia/Tokyo"}},
            action=action)
        out["created"] = _as_dict(created)
    except Exception as e:  # noqa: BLE001
        out["create_error"] = f"{type(e).__name__}: {e}"[:800]
        return out

    before = _tool_calls(container)
    try:
        out["dispatch_local"] = _as_dict(routines.dispatch(routine_name=name))
    except Exception as e:  # noqa: BLE001
        out["dispatch_local_error"] = f"{type(e).__name__}: {e}"[:800]
    out["runs_after_local"] = _wait_runs(routines, name, 1)
    time.sleep(60)  # エージェントの仕事はバックグラウンドで続く
    out["tool_calls_added_local"] = _tool_calls(container) - before

    before = _tool_calls(container)
    out["dispatch_functions"] = queue_probe(env, {"kind": "routine", "routine": name})
    out["runs_after_functions"] = _wait_runs(routines, name, 2)
    time.sleep(60)
    out["tool_calls_added_functions"] = _tool_calls(container) - before
    return out


def main() -> None:
    env = azd_env()
    project = project_client(env)
    routines = project.beta.routines
    container = ContainerClient(f"https://{env['STORAGE_ACCOUNT_NAME']}.blob.core.windows.net", "probe-results",
                                credential=DefaultAzureCredential())
    results = {}
    try:
        results["A_no_conversation"] = _try("spike-morning-a", routines, env, container, None)
        conv = project.get_openai_client(agent_name=AGENT).conversations.create()
        results["B_with_conversation"] = _try("spike-morning-b", routines, env, container, conv.id)
    finally:
        for name in ("spike-morning-a", "spike-morning-b"):
            try:
                routines.delete(name)
            except Exception:  # noqa: BLE001
                pass
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str)[:6000])
    save("routines", results)


if __name__ == "__main__":
    main()
