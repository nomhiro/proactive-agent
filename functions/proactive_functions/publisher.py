"""画面への通知（Web PubSub）。送るのは「再読み込みの合図」だけ（計画の決定9）。

合図: {"type": "refresh", "kind": <コンテナー名>, "id": <文書 ID>, "team": <チーム>}
グループ名はチームの値。同じ合図が二度届いても、画面が読み直すだけで害はない。
配達前の通知と、それにひもづくメッセージは合図を送らない。
"""

from typing import Protocol

from azure.messaging.webpubsubservice import WebPubSubServiceClient
from vehicle_core.constants import Team

from .store import Store

PUBLISHED_CONTAINERS = ("messages", "proposals", "agent_runs", "notifications", "watches")


class Publisher(Protocol):
    def publish(self, team: Team, event: dict) -> None: ...


def refresh_event(kind: str, id_: str, team: str) -> dict:
    return {"type": "refresh", "kind": kind, "id": id_, "team": team}


class WebPubSubPublisher:
    def __init__(self, endpoint: str, hub: str, credential) -> None:
        self._client = WebPubSubServiceClient(endpoint=endpoint, hub=hub, credential=credential)

    def publish(self, team: Team, event: dict) -> None:
        self._client.send_to_group(group=Team(team).value, message=event, content_type="application/json")


def _held(container: str, doc: dict, store: Store) -> bool:
    if container == "notifications":
        return doc.get("delivered_at") is None
    if container == "messages" and doc.get("notification_id"):
        n = store.get("notifications", doc["notification_id"])
        return n is None or n.get("delivered_at") is None
    return False


def publish_changes(container: str, docs: list[dict], store: Store, publisher: Publisher) -> int:
    sent = 0
    for doc in docs:
        if doc.get("origin") == "seed" or not doc.get("team") or _held(container, doc, store):
            continue
        publisher.publish(doc["team"], refresh_event(container, doc["id"], doc["team"]))
        sent += 1
    return sent
