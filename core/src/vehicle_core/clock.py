"""JST の時計。デモでは仮想の時計で時間を進める。"""

from datetime import datetime, time, timedelta
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


def crossed_morning(before: datetime, after: datetime, at: time | None = None) -> bool:
    """JST で before < 朝の時刻 <= after となる朝（既定 8:00）が1つでもあれば真。"""
    from .constants import DIGEST_TIME

    at = at or DIGEST_TIME
    before, after = to_jst(before), to_jst(after)
    if after <= before:
        return False
    first = datetime.combine(before.date(), at, tzinfo=JST)
    if first <= before:
        first += timedelta(days=1)
    return first <= after
