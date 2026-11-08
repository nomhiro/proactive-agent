"""Functions の設定（アプリ設定の環境変数）。キーや接続文字列は持たない。"""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel


class Settings(BaseModel):
    cosmos_endpoint: str
    cosmos_database: str
    webpubsub_endpoint: str
    webpubsub_hub: str
    gateway_tenant_id: str
    gateway_audiences: list[str]
    agent_invoker: Literal["log"] = "log"
    # HILS ログを読む Blob のエンドポイント。なければ get_test_log は「ログがありません」を返す
    blob_endpoint: str | None = None


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    return Settings(
        cosmos_endpoint=env["COSMOS_ENDPOINT"],
        cosmos_database=env.get("COSMOS_DATABASE", "proactive"),
        webpubsub_endpoint=env["WEBPUBSUB_ENDPOINT"],
        webpubsub_hub=env.get("WEBPUBSUB_HUB", "proactive"),
        gateway_tenant_id=env["GATEWAY_TENANT_ID"],
        gateway_audiences=[a.strip() for a in env["GATEWAY_AUDIENCES"].split(",") if a.strip()],
        agent_invoker=env.get("AGENT_INVOKER", "log"),
        blob_endpoint=env.get("AZURE_STORAGE_BLOB_ENDPOINT") or None,
    )
