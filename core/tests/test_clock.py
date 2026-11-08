from datetime import datetime, timedelta, timezone

import pytest

from vehicle_core.clock import VirtualClock, to_jst
from vehicle_core.constants import JST


def test_to_jst_converts_utc():
    utc = datetime(2026, 11, 17, 12, 10, tzinfo=timezone.utc)
    assert to_jst(utc) == datetime(2026, 11, 17, 21, 10, tzinfo=JST)


def test_to_jst_rejects_naive():
    with pytest.raises(ValueError):
        to_jst(datetime(2026, 11, 17, 21, 10))


def test_virtual_clock_advance_and_set():
    c = VirtualClock(datetime(2026, 11, 17, 21, 10, tzinfo=JST))
    c.advance(timedelta(hours=11))
    assert c.now() == datetime(2026, 11, 18, 8, 10, tzinfo=JST)
    c.set(datetime(2026, 11, 23, 8, 0, tzinfo=JST))
    assert c.now().day == 23


def test_virtual_clock_rejects_naive_start():
    with pytest.raises(ValueError):
        VirtualClock(datetime(2026, 11, 17))


def jst(*a):
    return datetime(*a, tzinfo=JST)


def test_crossed_morning():
    from vehicle_core.clock import crossed_morning
    assert crossed_morning(jst(2026, 11, 17, 21, 10), jst(2026, 11, 18, 8, 0))
    assert not crossed_morning(jst(2026, 11, 18, 8, 0), jst(2026, 11, 18, 9, 0))
    assert crossed_morning(jst(2026, 11, 19, 9, 0), jst(2026, 11, 23, 7, 0))
    assert not crossed_morning(jst(2026, 11, 18, 9, 0), jst(2026, 11, 18, 15, 0))
    assert not crossed_morning(jst(2026, 11, 18, 9, 0), jst(2026, 11, 18, 9, 0))
