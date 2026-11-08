"""JST の時計。デモでは仮想の時計で時間を進める。"""

from datetime import datetime, timedelta
from typing import Protocol

from .constants import JST


def to_jst(dt: datetime) -> datetime:
    """タイムゾーン付きの日時を JST に直す。タイムゾーンなしは ValueError。"""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"タイムゾーンのない日時は受け付けません: {dt!r}")
    return dt.astimezone(JST)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(JST)


class VirtualClock:
    def __init__(self, start: datetime) -> None:
        self._now = to_jst(start)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta

    def set(self, dt: datetime) -> None:
        self._now = to_jst(dt)
