"""Azure 上で Plan 2 の流れを通して確かめるスモークテスト。

使い方: uv run --package proactive-functions python scripts/smoke.py

確かめること（設計書 9 章の「二重通知がないこと」「権限」の一部）:
  1. シードを作り直す
  2. 21:10 に s1 の変更イベントを書くと、まとめの窓（180 秒）を越えた 21:14 に調査依頼がエージェントに渡る
  3. 同じ変更イベントをもう一度流しても、調査依頼は1件のまま
  4. トークンなし、宛先の違うトークンでは書き込み窓口が 401 を返す
  5. 最後にシードを作り直して元に戻す

注意: Azure 上のデモのデータを消して作り直す。
"""

import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _azd import cosmos_store, env  # noqa: E402
from vehicle_core.constants import JST, Team  # noqa: E402
from vehicle_core.routing import idempotency_key  # noqa: E402
from vehicle_core.scenarios import SCENARIOS  # noqa: E402

from proactive_functions.clock import set_virtual_now  # noqa: E402
from proactive_functions.seeding import seed_store  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'NG'}] {name} {detail}", flush=True)


def wait_until(predicate, timeout: float, interval: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def post(url: str, token: str | None) -> int:
    req = urllib.request.Request(url, data=b'{"id": "smoke"}', method="POST",
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def records_for(store, source_id: str) -> list[dict]:
    return [d for d in store.query("investigations") if source_id in d.get("source_ids", [])]


def main() -> int:
    store = cosmos_store()
    event = SCENARIOS["s1_signal_period"].steps[0].change
    request_id = idempotency_key(Team.INTEGRATED_CONTROL, "change", [event.id])

    seed_store(store, reset=True, system_now=datetime.now(JST))
    check("シードの作り直し", store.get("artifacts", "SIG-BrkPedalPos") is not None)

    set_virtual_now(store, datetime(2026, 11, 17, 21, 10, tzinfo=JST), datetime.now(JST))
    store.create("change_events", event.model_dump(mode="json"))
    pending = wait_until(lambda: store.get("investigations", request_id), timeout=180)
    check("変更イベントから調査依頼ができる", pending is not None,
          f"(team={pending and pending['team']}, floor={pending and pending['floor']})")

    set_virtual_now(store, datetime(2026, 11, 17, 21, 14, tzinfo=JST), datetime.now(JST))
    done = wait_until(lambda: (d := store.get("investigations", request_id)) and d["status"] == "dispatched" and d,
                      timeout=150)
    check("まとめの窓を越えるとエージェントに渡る", done is not None,
          f"(status={(done or store.get('investigations', request_id) or {}).get('status')})")

    store.upsert("change_events", event.model_dump(mode="json"))
    time.sleep(60)
    count = len(records_for(store, event.id))
    check("同じ変更を二度流しても依頼は1件", count == 1, f"(件数={count})")

    url = f"{env('FUNCTION_APP_URL')}/api/agent/messages"
    check("トークンなしは 401", (status := post(url, None)) == 401, f"(status={status})")
    mgmt = subprocess.run(["az", "account", "get-access-token", "--query", "accessToken", "-o", "tsv"],
                          capture_output=True, text=True, shell=sys.platform == "win32").stdout.strip()
    check("宛先の違うトークンは 401", (status := post(url, mgmt)) == 401, f"(status={status})")

    seed_store(store, reset=True, system_now=datetime.now(JST))
    check("後片付け（シードの作り直し）", store.query("investigations") == [])

    ok = all(r[1] for r in results)
    print("SMOKE OK" if ok else "SMOKE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
