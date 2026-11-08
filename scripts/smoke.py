"""Azure 上で Plan 3 の流れ（エージェント4体まで）を通して確かめるスモークテスト。

使い方: uv run --package proactive-functions python scripts/smoke.py

確かめること（設計書 9 節の「二重通知がないこと」「権限」の一部と、シナリオ1の前半）:
  1. シードを作り直す
  2. トークンなしの MCP サーバーへの呼び出しは 401
  3. エージェント4体の ID に、Cosmos DB のデータ権限が1つもない
  4. 21:10 に s1 の変更イベントを書き、21:14 に進めると、統合制御のエージェントが調査して作業記録を閉じ、
     BrkPedalPos を起点に notify_now の通知を1件記録する。届けるのは翌朝 8:00
  5. 統合制御から、モーター制御宛ての impact_notice の下書き（承認待ち）ができる
  6. 時計を 11/18 08:00 に進めると、朝のまとめが Routines で起動する。もう一度起動しても、まとめは増えない
  7. 最後にシードを作り直して元に戻す

LLM が書いた文章は判定しない。待ち合わせは5秒ごとに読み直し、上限時間で打ち切る。
注意: Azure 上のデモのデータを消して作り直す。モデルの呼び出しの費用が少しかかる。
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _azd import cosmos_store, env  # noqa: E402
from vehicle_core.constants import AGENT_TEAMS, JST, Team, agent_name  # noqa: E402
from vehicle_core.routing import idempotency_key  # noqa: E402
from vehicle_core.scenarios import SCENARIOS  # noqa: E402

from proactive_functions.clock import set_virtual_now  # noqa: E402
from proactive_functions.seeding import seed_store  # noqa: E402

POLL = 5.0
IC = Team.INTEGRATED_CONTROL
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'NG'}] {name} {detail}", flush=True)


def wait_until(predicate, timeout: float, interval: float = POLL):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def post_mcp(url: str) -> int:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def az(*args: str) -> str:
    r = subprocess.run(["az", *args], capture_output=True, text=True, shell=sys.platform == "win32")
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:800])
    return r.stdout


def project_client():
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential
    return AIProjectClient(endpoint=env("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential(),
                           allow_preview=True)


def agent_principals(project) -> dict[str, str]:
    out = {}
    for team in sorted(AGENT_TEAMS, key=lambda t: t.value):
        ident = project.agents.get(agent_name(team)).as_dict().get("instance_identity") or {}
        out[team.value] = ident.get("principal_id", "")
    return out


def cosmos_principals() -> set[str]:
    account = urlparse(env("COSMOS_ENDPOINT")).hostname.split(".")[0]
    raw = az("cosmosdb", "sql", "role", "assignment", "list", "--account-name", account,
             "--resource-group", env("AZURE_RESOURCE_GROUP"), "-o", "json")
    return {a["principalId"] for a in json.loads(raw)}


def s1_notification(store) -> dict | None:
    for n in store.query("notifications", {"team": IC.value}):
        if n.get("origin_artifact_id") == "SIG-BrkPedalPos" and n.get("classification") == "notify_now":
            return n
    return None


def impact_notice_to_motor(store) -> dict | None:
    for p in store.query("proposals", {"team": IC.value}):
        if p.get("kind") == "impact_notice" and Team.MOTOR_CONTROL.value in p.get("to_teams", []) \
                and p.get("status") == "pending":
            return p
    return None


def main() -> int:
    store = cosmos_store()
    project = project_client()
    event = SCENARIOS["s1_signal_period"].steps[0].change
    request_id = idempotency_key(IC, "change", [event.id])
    run_id = f"run-inv-{request_id}"
    morning_id = f"run-morning-{IC.value}-20261118"

    seed_store(store, reset=True, system_now=datetime.now(JST))
    check("シードの作り直し", store.get("artifacts", "SIG-BrkPedalPos") is not None)

    url = f"{env('FUNCTION_APP_URL')}/api/mcp"
    check("トークンなしの MCP は 401", (status := post_mcp(url)) == 401, f"(status={status})")

    principals = agent_principals(project)
    leaked = {t: p for t, p in principals.items() if p and p in cosmos_principals()}
    check("エージェントの ID に Cosmos のデータ権限がない", all(principals.values()) and not leaked,
          f"(agents={len([p for p in principals.values() if p])}, leaked={leaked})")

    time.sleep(70)  # 作り直した直後の tick が last_tick を書き終えるのを待つ（時計を動かした判定の基準）
    set_virtual_now(store, datetime(2026, 11, 17, 21, 10, tzinfo=JST), datetime.now(JST))
    store.create("change_events", event.model_dump(mode="json"))
    pending = wait_until(lambda: store.get("investigations", request_id), timeout=180)
    check("変更イベントから調査依頼ができる", pending is not None)

    set_virtual_now(store, datetime(2026, 11, 17, 21, 14, tzinfo=JST), datetime.now(JST))
    run = wait_until(lambda: (d := store.get("agent_runs", run_id)) and d.get("state") == "done" and d, timeout=600)
    current = store.get("agent_runs", run_id) or {}
    check("統合制御のエージェントが調査して作業記録を閉じる", run is not None,
          f"(state={current.get('state')}, detail={json.dumps(current.get('detail', {}), ensure_ascii=False)[:300]})")

    note = s1_notification(store)
    check("BrkPedalPos を起点に notify_now の通知が1件", note is not None,
          f"(件数={sum(1 for n in store.query('notifications', {'team': IC.value}))})")
    deliver_at = (note or {}).get("deliver_at") or ""
    check("届けるのは翌朝 8:00", deliver_at.startswith("2026-11-18T08:00"), f"(deliver_at={deliver_at})")

    proposal = impact_notice_to_motor(store)
    check("モーター制御宛ての impact_notice の下書きができる", proposal is not None,
          f"(提案={[(p.get('kind'), p.get('to_teams')) for p in store.query('proposals', {'team': IC.value})]})")

    set_virtual_now(store, datetime(2026, 11, 18, 8, 0, tzinfo=JST), datetime.now(JST))
    morning = wait_until(lambda: (d := store.get("agent_runs", morning_id)) and d.get("state") == "done" and d,
                         timeout=300)
    check("朝のまとめが起動して閉じる", morning is not None,
          f"(state={(store.get('agent_runs', morning_id) or {}).get('state')})")

    before = len(store.query("messages", {"team": IC.value}))
    project.beta.routines.dispatch(routine_name=f"morning-{agent_name(IC)}")
    time.sleep(120)
    after = len(store.query("messages", {"team": IC.value}))
    check("もう一度起動しても朝のまとめは増えない", after == before, f"(前={before}, 後={after})")

    seed_store(store, reset=True, system_now=datetime.now(JST))
    check("後片付け（シードの作り直し）", store.query("investigations") == [])

    ok = all(r[1] for r in results)
    print("SMOKE OK" if ok else "SMOKE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
