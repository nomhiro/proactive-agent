"""デモのシナリオを1手ずつ進める CLI（設計書 5.3 節）。画面の「デモの操作」と同じ仕組みを使う。

使い方:
  uv run --package proactive-web python scripts/scenario.py list          # 手順の一覧（済んだものに印）
  uv run --package proactive-web python scripts/scenario.py next [--wait] # 次の手順を行う
  uv run --package proactive-web python scripts/scenario.py reset         # 最初からやり直す

注意: reset は Azure 上のデモのデータを消して作り直す。
--wait を付けると、人の発言の手順のあと、アシスタントの返事が画面の会話に書き写されるまで待つ（上限5分）。
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _azd import cosmos_store, env  # noqa: E402
from azure.identity import DefaultAzureCredential  # noqa: E402

from proactive_functions.clock import StoredClock  # noqa: E402
from proactive_web.chat import ChatService, FoundryChatClient  # noqa: E402
from proactive_web.scenario_runner import ScenarioRunner, StepNotReady  # noqa: E402

WAIT_LIMIT = 300.0
POLL = 5.0


def build_runner() -> tuple[ScenarioRunner, ChatService]:
    store = cosmos_store()
    chat = ChatService(store, FoundryChatClient(env("FOUNDRY_PROJECT_ENDPOINT"), DefaultAzureCredential()),
                       StoredClock(store).now)
    return ScenarioRunner(store, chat), chat


def show(runner: ScenarioRunner) -> None:
    for s in runner.steps():
        print(f"{'済' if s['done'] else '  '} {s['index']:2d} [{s['scenario_title']}] {s['summary']}")


def wait_for_reply(chat: ChatService, step: dict) -> None:
    from vehicle_core.scenarios import StepKind
    if step["kind"] != StepKind.HUMAN_SAYS.value:
        return
    deadline = time.monotonic() + WAIT_LIMIT
    while time.monotonic() < deadline:
        chat.sync()
        if not chat.busy(None):
            print("返事が届きました")
            return
        time.sleep(POLL)
    print("返事を待ちきれませんでした（画面を開くか、もう一度 next --wait で受け取れます）")


def main() -> int:
    parser = argparse.ArgumentParser(description="デモのシナリオを1手ずつ進める")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="手順の一覧")
    nxt = sub.add_parser("next", help="次の手順を行う")
    nxt.add_argument("--wait", action="store_true", help="人の発言のあと、返事が書き写されるまで待つ")
    sub.add_parser("reset", help="Azure 上のデモのデータを消して作り直す")
    args = parser.parse_args()

    runner, chat = build_runner()
    if args.command == "list":
        show(runner)
    elif args.command == "reset":
        runner.reset()
        print("デモのデータを作り直しました")
    else:
        chat.sync()
        try:
            step = runner.next()
        except StepNotReady as e:
            print(f"まだ進められません: {e.reason}")
            return 1
        print(f"行いました: {step['summary']}")
        if args.wait:
            wait_for_reply(chat, step)
    return 0


if __name__ == "__main__":
    sys.exit(main())
