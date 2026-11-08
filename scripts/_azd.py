"""scripts/ の共通処理: azd の環境の値と、Cosmos の Store を用意する。

azd のフックから動くときは、azd の環境の値が環境変数で渡る。
手で動かすときは `azd env get-values` から読む。
"""

import os
import subprocess

from azure.identity import DefaultAzureCredential

from proactive_functions.store import CosmosStore


def env(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    out = subprocess.run(["azd", "env", "get-value", name], capture_output=True, text=True, check=False)
    value = out.stdout.strip()
    if out.returncode != 0 or not value:
        raise SystemExit(f"{name} がわかりません。azd up を済ませるか、環境変数で渡してください")
    return value


def cosmos_store() -> CosmosStore:
    return CosmosStore(env("COSMOS_ENDPOINT"), env("COSMOS_DATABASE"), DefaultAzureCredential())
