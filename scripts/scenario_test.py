"""シナリオテスト（設計書 9 節）。5つのシナリオを Azure 上で本物の LLM で最初から通し、構造化された結果で判定する。

使い方: uv run --package proactive-web python scripts/scenario_test.py

- 手順ごとに web/proactive_web/scenario_checks.py の期待値を5秒ごとに読み直し、上限まで待つ
- 満たせなくても次の手順に進む。最後に OK / NG の一覧を出し、NG があれば終了コード 1
- 追加で確かめること: 同じ変更イベントを2回流しても通知が増えない／朝のまとめをもう一度起動しても増えない

注意: Azure 上のデモのデータを消して作り直す。モデルの呼び出しの費用がかかる（全体で 40 分ほど）。
終わったあとはデータを残すので、画面で結果を見られる。
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _azd import cosmos_store, env  # noqa: E402
from azure.identity import DefaultAzureCredential  # noqa: E402
from vehicle_core.constants import AGENT_TEAMS, Team  # noqa: E402
from vehicle_core.scenarios import SCENARIOS  # noqa: E402

from proactive_functions.clock import StoredClock  # noqa: E402
from proactive_functions.foundry_invoker import FoundryRoutineDispatcher  # noqa: E402
from proactive_web.app import FoundryMemoryReader  # noqa: E402
from proactive_web.chat import ChatService, FoundryChatClient  # noqa: E402
from proactive_web.scenario_checks import EXPECTATIONS, CheckContext, snapshot  # noqa: E402
from proactive_web.scenario_runner import ScenarioRunner, StepNotReady  # noqa: E402

POLL = 5.0
STEP_READY_LIMIT = 600.0  # 時計の手順は、メールから起きる調査まで終わるのを待つ
DUPLICATE_WAIT = 90.0
REDISPATCH_WAIT = 120.0
IC = Team.INTEGRATED_CONTROL.value
results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'NG'}] {name} {detail}", flush=True)


def safe(predicate, ctx) -> tuple[bool, str]:
    try:
        return bool(predicate(ctx)), ""
    except Exception as e:  # noqa: BLE001 — 判定の失敗は NG として記録して続ける
        return False, f"（判定で例外: {e!r}）"


def wait(chat: ChatService, predicate, ctx, timeout: float) -> tuple[bool, str, float]:
    start = time.monotonic()
    while True:
        chat.sync()
        ok, detail = safe(predicate, ctx)
        elapsed = time.monotonic() - start
        if ok or elapsed >= timeout:
            return ok, detail, elapsed
        time.sleep(POLL)


def apply_step(runner: ScenarioRunner, chat: ChatService) -> dict | None:
    deadline = time.monotonic() + STEP_READY_LIMIT
    while True:
        chat.sync()
        try:
            return runner.next()
        except StepNotReady as e:
            if time.monotonic() >= deadline:
                record("手順を進める", False, f"（{e.reason}）")
                return None
            time.sleep(POLL)


def check_no_duplicate(store, chat: ChatService) -> None:
    """同じ変更イベントをもう一度流しても、調査依頼と通知が増えない（設計書 9 節）。"""
    event = SCENARIOS["s1_signal_period"].steps[0].change
    before = (len(store.query("investigations", {"team": IC})), len(store.query("notifications", {"team": IC})))
    store.upsert("change_events", event.model_dump(mode="json"))
    time.sleep(DUPLICATE_WAIT)
    chat.sync()
    after = (len(store.query("investigations", {"team": IC})), len(store.query("notifications", {"team": IC})))
    record("同じ変更イベントを2回流しても、調査依頼と通知が増えない", before == after, f"（前 {before} → 後 {after}）")


def check_morning_once(store, endpoint: str, credential) -> None:
    """朝のまとめを手動でもう一度起動しても、作業記録と朝のメッセージが増えない。"""
    def counts():
        runs = [r for r in store.query("agent_runs") if r["id"].startswith("run-morning-")]
        return len(runs), len(store.query("messages"))
    before = counts()
    dispatcher = FoundryRoutineDispatcher(endpoint, credential)
    for team in sorted(AGENT_TEAMS, key=lambda t: t.value):
        dispatcher.dispatch(team)
    time.sleep(REDISPATCH_WAIT)
    after = counts()
    record("朝のまとめをもう一度起動しても、まとめが増えない", before == after, f"（前 {before} → 後 {after}）")


def main() -> int:
    credential = DefaultAzureCredential()
    endpoint = env("FOUNDRY_PROJECT_ENDPOINT")
    store = cosmos_store()
    chat = ChatService(store, FoundryChatClient(endpoint, credential), StoredClock(store).now)
    memory = FoundryMemoryReader(endpoint, credential, env("MEMORY_STORE_NAME"))
    runner = ScenarioRunner(store, chat)

    runner.reset()
    record("シードの作り直し", store.get("artifacts", "SIG-BrkPedalPos") is not None)

    per_scenario: dict[str, int] = {}
    for view in runner.steps():
        n = per_scenario.get(view["scenario_id"], 0)
        per_scenario[view["scenario_id"]] = n + 1
        key = f"{view['scenario_id']}#{n}"
        print(f"\n--- {key}: {view['summary']}", flush=True)
        before = snapshot(store)
        if apply_step(runner, chat) is None:
            continue
        ctx = CheckContext(store=store, memory=memory, before_ids=before)
        checks = EXPECTATIONS.get(key, [])
        for c in (c for c in checks if not c.final):
            ok, detail, elapsed = wait(chat, c.predicate, ctx, c.timeout_s)
            record(f"{key} {c.name}", ok, detail or f"（{elapsed:.0f} 秒）")
        for c in (c for c in checks if c.final):
            ok, detail = safe(c.predicate, ctx)
            record(f"{key} {c.name}", ok, detail)
        if key == "s1_signal_period#0":
            check_no_duplicate(store, chat)
        if key == "s3_morning#0":
            check_morning_once(store, endpoint, credential)

    failed = [r for r in results if not r[1]]
    print(f"\n結果: OK {len(results) - len(failed)} / NG {len(failed)}")
    for name, _, detail in failed:
        print(f"  NG: {name} {detail}")
    print("SCENARIO OK" if not failed else "SCENARIO NG")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
