from datetime import datetime, timedelta

from vehicle_core.clock import VirtualClock
from vehicle_core.constants import JST

from proactive_functions.clock import StoredClock, set_virtual_now
from tests.fakes import MemoryStore


def test_stored_clock_applies_offset():
    store = MemoryStore()
    real = VirtualClock(datetime(2026, 11, 8, 12, 0, tzinfo=JST))
    set_virtual_now(store, datetime(2026, 11, 17, 21, 10, tzinfo=JST), real.now())
    clock = StoredClock(store, real)
    assert clock.now() == datetime(2026, 11, 17, 21, 10, tzinfo=JST)
    real.advance(timedelta(minutes=4))  # 実時間が流れると仮想時計も流れる
    assert clock.now() == datetime(2026, 11, 17, 21, 14, tzinfo=JST)


def test_stored_clock_without_document_is_real_time():
    real = VirtualClock(datetime(2026, 11, 8, 12, 0, tzinfo=JST))
    assert StoredClock(MemoryStore(), real).now() == real.now()


def test_set_virtual_now_overwrites_previous_offset():
    store = MemoryStore()
    real = VirtualClock(datetime(2026, 11, 8, 12, 0, tzinfo=JST))
    set_virtual_now(store, datetime(2026, 11, 17, 21, 10, tzinfo=JST), real.now())
    set_virtual_now(store, datetime(2026, 11, 18, 8, 0, tzinfo=JST), real.now())
    assert StoredClock(store, real).now() == datetime(2026, 11, 18, 8, 0, tzinfo=JST)
    assert store.get("system", "clock")["vehicle_id"] == "kakuu-suv"
