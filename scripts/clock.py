"""仮想時計の表示と設定。時計を合わせると、Functions の tick がすぐに動く。

使い方:
  uv run --package proactive-functions python scripts/clock.py show
  uv run --package proactive-functions python scripts/clock.py set 2026-11-18T08:00:00+09:00
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _azd import cosmos_store  # noqa: E402
from vehicle_core.clock import to_jst  # noqa: E402
from vehicle_core.constants import JST  # noqa: E402

from proactive_functions.clock import CLOCK_CONTAINER, CLOCK_ID, StoredClock, set_virtual_now  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="仮想時計の表示と設定")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="いまの仮想時刻を表示する")
    set_cmd = sub.add_parser("set", help="仮想時刻を合わせる")
    set_cmd.add_argument("at", help="タイムゾーン付きの ISO 8601（例: 2026-11-18T08:00:00+09:00）")
    args = parser.parse_args()

    store = cosmos_store()
    if args.command == "set":
        target = to_jst(datetime.fromisoformat(args.at))
        set_virtual_now(store, target, datetime.now(JST))
    doc = store.get(CLOCK_CONTAINER, CLOCK_ID)
    offset = doc["offset_seconds"] if doc else 0.0
    print(f"仮想時刻: {StoredClock(store).now():%Y-%m-%d %H:%M:%S %Z}（実時間とのずれ {offset:+.0f} 秒）")


if __name__ == "__main__":
    main()
