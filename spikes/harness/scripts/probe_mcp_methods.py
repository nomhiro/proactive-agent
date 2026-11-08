"""Plan 3 決定 2: Foundry が MCP のどのメソッドにトークンを付けるかを、Functions が Blob に残した記録から読む。

先に `python scripts/probe.py mcp` を流してから実行する。
"""

import json

from _env import azd_env, save
from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient


def main() -> None:
    env = azd_env()
    container = ContainerClient(f"https://{env['STORAGE_ACCOUNT_NAME']}.blob.core.windows.net", "probe-results",
                                credential=DefaultAzureCredential())
    records = []
    for b in sorted(container.list_blobs(name_starts_with="mcp-log/"), key=lambda b: b.name):
        records.append({"blob": b.name, **json.loads(container.download_blob(b.name).readall())})
    summary: dict[str, set] = {}
    for r in records:
        for m in r["methods"]:
            summary.setdefault(m, set()).add(f"auth={r['has_authorization']} verified={r['verified']}")
    out = {"summary": {k: sorted(v) for k, v in summary.items()}, "records": records}
    print(json.dumps(out["summary"], ensure_ascii=False, indent=2))
    save("mcp-methods", out)


if __name__ == "__main__":
    main()
