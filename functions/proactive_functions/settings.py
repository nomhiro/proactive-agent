"""Functions の設定（アプリ設定の環境変数）。キーや接続文字列は持たない。"""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, model_validator


class Settings(BaseModel):
    cosmos_endpoint: str
    cosmos_database: str
    webpubsub_endpoint: str
    webpubsub_hub: str
    gateway_tenant_id: str
    gateway_audiences: list[str]
    # log: ログに出すだけ（Plan 2）。foundry: Foundry のエージェントを起動する（Plan 3）
    agent_invoker: Literal["log", "foundry"] = "log"
    # HILS ログを読む Blob のエンドポイント。なければ get_test_log は「ログがありません」を返す
    blob_endpoint: str | None = None
    # Foundry のプロジェクト（記憶とエージェントの起動に使う）
    foundry_project_endpoint: str | None = None
    # チームの記憶を置く Memory ストアの名前。なければ記憶の道具は「設定されていません」を返す
    memory_store_name: str | None = None

    @model_validator(mode="after")
    def _foundry_needs_endpoint(self) -> "Settings":
        if self.agent_invoker == "foundry" and not self.foundry_project_endpoint:
            raise ValueError("AGENT_INVOKER=foundry には FOUNDRY_PROJECT_ENDPOINT が要ります")
        return self


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
        foundry_project_endpoint=env.get("FOUNDRY_PROJECT_ENDPOINT") or None,
        memory_store_name=env.get("MEMORY_STORE_NAME") or None,
    )
