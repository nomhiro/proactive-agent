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


def test_stored_clock_read_returns_now_and_offset_together():  # tick の朝の Routines の判定に使う（Plan 3 決定 17）
    store = MemoryStore()
    real = VirtualClock(datetime(2026, 11, 8, 12, 0, tzinfo=JST))
    set_virtual_now(store, datetime(2026, 11, 8, 13, 0, tzinfo=JST), real.now())
    now, offset = StoredClock(store, real).read()
    assert now == datetime(2026, 11, 8, 13, 0, tzinfo=JST) and offset == 3600.0
    assert StoredClock(MemoryStore(), real).read() == (real.now(), 0.0)


def test_reader_with_slower_clock_never_sees_before_target():  # シナリオテスト: PC の時計が 0.5 秒進んでいると 7:59:59 に見えた
    store = MemoryStore()
    setter = datetime(2026, 11, 9, 10, 51, 13, 500000, tzinfo=JST)
    set_virtual_now(store, datetime(2026, 11, 18, 8, 0, tzinfo=JST), setter)
    functions_real = VirtualClock(setter - timedelta(seconds=0.4))  # Functions の時計は 0.5 秒遅れ、0.1 秒後に読む
    assert StoredClock(store, functions_real).now() == datetime(2026, 11, 18, 8, 0, tzinfo=JST)
    functions_real.advance(timedelta(seconds=10))  # ずれより長く経てば、ふつうに流れる
    assert StoredClock(store, functions_real).now() == datetime(2026, 11, 18, 8, 0, 9, 600000, tzinfo=JST)
