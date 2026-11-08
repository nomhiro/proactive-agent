"""画面への通知（Web PubSub）。送るのは「再読み込みの合図」だけ（計画の決定9）。"""

from typing import Protocol

from vehicle_core.constants import Team


class Publisher(Protocol):
    def publish(self, team: Team, event: dict) -> None: ...


def refresh_event(kind: str, id_: str, team: str) -> dict:
    return {"type": "refresh", "kind": kind, "id": id_, "team": team}
