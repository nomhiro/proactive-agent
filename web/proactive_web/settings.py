"""Web アプリの設定（環境変数）。キーや接続文字列は持たない。"""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, model_validator


class WebSettings(BaseModel):
    # cosmos: Azure の Cosmos DB。memory: ローカルの確認用（決定 20）
    store: Literal["cosmos", "memory"] = "cosmos"
    # easyauth: Container Apps の組み込み認証のヘッダーを読む。off: ローカルの確認用
    auth: Literal["easyauth", "off"] = "easyauth"
    cosmos_endpoint: str | None = None
    cosmos_database: str = "proactive"
    foundry_project_endpoint: str | None = None
    memory_store_name: str | None = None
    webpubsub_endpoint: str | None = None
    webpubsub_hub: str = "proactive"

    @model_validator(mode="after")
    def _cosmos_needs_endpoint(self) -> "WebSettings":
        if self.store == "cosmos" and not self.cosmos_endpoint:
            raise ValueError("WEB_STORE=cosmos には COSMOS_ENDPOINT が要ります")
        return self


def load_settings(env: Mapping[str, str] = os.environ) -> WebSettings:
    def opt(name: str) -> str | None:
        return env.get(name) or None

    return WebSettings(
        store=env.get("WEB_STORE", "cosmos"),
        auth=env.get("WEB_AUTH", "easyauth"),
        cosmos_endpoint=opt("COSMOS_ENDPOINT"),
        cosmos_database=env.get("COSMOS_DATABASE", "proactive"),
        foundry_project_endpoint=opt("FOUNDRY_PROJECT_ENDPOINT"),
        memory_store_name=opt("MEMORY_STORE_NAME"),
        webpubsub_endpoint=opt("WEBPUBSUB_ENDPOINT"),
        webpubsub_hub=env.get("WEBPUBSUB_HUB", "proactive"),
    )
