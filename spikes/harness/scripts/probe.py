"""spike の確認を実行し、結果を results/ に JSON で残す。

  python scripts/probe.py mcp                    # spike 2: 2体に whoami を呼ばせ、トークンの中身を比べる
  python scripts/probe.py invoke --mode sync     # spike 6a: 手元から起動して応答を待つ
  python scripts/probe.py invoke --mode background  # spike 6b: background=True で投げて状態を見に行く
  python scripts/probe.py queue --mode background   # spike 6c: Functions（マネージド ID）から起動する
"""

import argparse
import json
import time
import uuid
from datetime import datetime

from _env import ROOT, azd_env
from azure.identity import DefaultAzureCredential
from spike_invoke import run_probe

RESULTS = ROOT / "results"
WHOAMI_PROMPT = "whoami ツールを1回呼び、返ってきた JSON をそのまま出力してください。"
# spike 3 も兼ねる: 作業環境で解析に使うライブラリが動くか
SHELL_PROMPT = (
    "シェルで次を実行し、出力をそのまま返してください: "
    "python -c \"import sys, numpy, scipy, matplotlib; print(sys.version); "
    "print(numpy.__version__, scipy.__version__, matplotlib.__version__)\""
)


def save(name: str, data) -> None:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{datetime.now():%Y%m%d-%H%M%S}-{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {path}")


def cmd_mcp(env: dict) -> None:
    credential = DefaultAzureCredential()
    results = [run_probe(env["FOUNDRY_PROJECT_ENDPOINT"], a, WHOAMI_PROMPT, "sync", credential)
               for a in ("spike-a", "spike-b")]
    for r in results:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    save("mcp", results)


def cmd_invoke(env: dict, mode: str) -> None:
    r = run_probe(env["FOUNDRY_PROJECT_ENDPOINT"], "spike-a", SHELL_PROMPT, mode, DefaultAzureCredential())
    r["caller"] = "local-user"
    print(json.dumps(r, ensure_ascii=False, indent=2))
    save(f"invoke-{mode}", r)


def cmd_queue(env: dict, mode: str) -> None:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.storage.blob import BlobClient
    from azure.storage.queue import QueueClient

    probe_id = uuid.uuid4().hex
    account_url = f"https://{env['STORAGE_ACCOUNT_NAME']}"
    credential = DefaultAzureCredential()
    message = json.dumps({"id": probe_id, "agent": "spike-a", "mode": mode, "prompt": SHELL_PROMPT}, ensure_ascii=False)
    QueueClient(f"{account_url}.queue.core.windows.net", "probe", credential=credential).send_message(message)
    print(f"queued {probe_id}; waiting for probe-results/{probe_id}.json")
    blob = BlobClient(f"{account_url}.blob.core.windows.net", "probe-results", f"{probe_id}.json", credential=credential)
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        try:
            r = json.loads(blob.download_blob().readall())
        except ResourceNotFoundError:
            time.sleep(10)
            continue
        print(json.dumps(r, ensure_ascii=False, indent=2))
        save(f"queue-{mode}", r)
        return
    raise SystemExit("timed out waiting for the Functions probe result")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mcp")
    for name in ("invoke", "queue"):
        s = sub.add_parser(name)
        s.add_argument("--mode", choices=["sync", "background"], default="sync")
    args = p.parse_args()
    env = azd_env()
    if args.cmd == "mcp":
        cmd_mcp(env)
    elif args.cmd == "invoke":
        cmd_invoke(env, args.mode)
    else:
        cmd_queue(env, args.mode)


if __name__ == "__main__":
    main()
