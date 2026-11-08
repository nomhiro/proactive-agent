"""Cosmos に置いた仮想時計（実時間 + ずれ）。Functions の中の現在時刻はすべてここから取る。

文書: system コンテナーの {"id": "clock", "vehicle_id": ..., "offset_seconds": float, "updated_at": ISO}
"""

from datetime import datetime, timedelta

from vehicle_core.clock import Clock, SystemClock, to_jst
from vehicle_core.constants import VEHICLE_ID

from .store import Store

CLOCK_CONTAINER = "system"
CLOCK_ID = "clock"


class StoredClock:
    def __init__(self, store: Store, system: Clock | None = None) -> None:
        self._store = store
        self._system = system or SystemClock()

    def now(self) -> datetime:
        return self.read()[0]

    def read(self) -> tuple[datetime, float]:
        """いまの仮想の時刻と、ずれ（秒）を、同じ文書から読む。"""
        doc = self._store.get(CLOCK_CONTAINER, CLOCK_ID)
        offset = float(doc["offset_seconds"]) if doc else 0.0
        return to_jst(self._system.now() + timedelta(seconds=offset)), offset


def set_virtual_now(store: Store, target: datetime, system_now: datetime) -> None:
    offset = (to_jst(target) - to_jst(system_now)).total_seconds()
    store.upsert(CLOCK_CONTAINER, {
        "id": CLOCK_ID,
        "vehicle_id": VEHICLE_ID,
        "offset_seconds": offset,
        "updated_at": to_jst(system_now).isoformat(),
    })
