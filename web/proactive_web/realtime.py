"""画面への合図（決定 16）。Web PubSub のクライアント用 URL を返す。

参加するグループは BFF が決めてトークンに入れる（画面に参加の操作をさせない）。
Functions の publisher は、文書のチームの値のグループに「再読み込みの合図」を送る。
"""

from typing import Protocol

TOKEN_MINUTES = 60


class RealtimeUrls(Protocol):
    def client_url(self, groups: list[str]) -> str | None: ...


class NoRealtime:
    """Web PubSub がないとき（ローカル）。画面は読み直しの間隔だけで動く。"""

    def client_url(self, groups: list[str]) -> str | None:
        return None


class WebPubSubUrls:
    def __init__(self, endpoint: str, hub: str, credential) -> None:
        from azure.messaging.webpubsubservice import WebPubSubServiceClient
        self._client = WebPubSubServiceClient(endpoint=endpoint, hub=hub, credential=credential)

    def client_url(self, groups: list[str]) -> str | None:
        token = self._client.get_client_access_token(groups=groups, minutes_to_expire=TOKEN_MINUTES)
        return token["url"]
