"""デモのデータを Cosmos に入れる。

使い方:
  uv run --package proactive-functions python scripts/seed.py           # 足りない文書だけ作る
  uv run --package proactive-functions python scripts/seed.py --reset   # すべて消して作り直す（時計も SEED_NOW に戻す）

--reset は Azure 上のデモのデータ（会話、提案、通知など）をすべて消す。
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _azd import cosmos_store  # noqa: E402
from vehicle_core.constants import JST  # noqa: E402

from proactive_functions.seeding import seed_store  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="デモのデータを Cosmos に入れる")
    parser.add_argument("--reset", action="store_true", help="leases 以外をすべて消して作り直す")
    args = parser.parse_args()
    counts = seed_store(cosmos_store(), reset=args.reset, system_now=datetime.now(JST))
    label = "作り直しました" if args.reset else "足りない文書を作りました"
    print(f"シード: {label}")
    for container, n in counts.items():
        print(f"  {container}: {n} 件")


if __name__ == "__main__":
    main()
