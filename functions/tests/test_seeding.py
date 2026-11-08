from datetime import datetime

from vehicle_core.clock import VirtualClock
from vehicle_core.constants import JST
from vehicle_core.seed import SEED_NOW

from proactive_functions.clock import StoredClock, set_virtual_now
from proactive_functions.seeding import DATA_CONTAINERS, seed_store
from tests.fakes import MemoryStore

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=JST)


def virtual_now(store):
    return StoredClock(store, VirtualClock(NOW)).now()


def test_data_containers_exclude_leases():
    assert len(DATA_CONTAINERS) == 13 and "leases" not in DATA_CONTAINERS and "investigations" in DATA_CONTAINERS


def test_seed_into_empty_store():
    store = MemoryStore()
    counts = seed_store(store, reset=False, system_now=NOW)
    assert counts["artifacts"] == 43 and counts["test_runs"] == 26
    assert counts["team_settings"] == 7 and counts["schedules"] == 1
    assert all(d["origin"] == "seed" for d in store.query("test_runs"))
    assert virtual_now(store) == SEED_NOW


def test_seed_without_reset_keeps_existing_and_clock():
    store = MemoryStore()
    seed_store(store, reset=False, system_now=NOW)
    set_virtual_now(store, datetime(2026, 11, 20, 9, 0, tzinfo=JST), NOW)
    store.create("messages", {"id": "m1", "vehicle_id": "kakuu-suv", "team": "integrated_control"})
    counts = seed_store(store, reset=False, system_now=NOW)
    assert counts["artifacts"] == 0 and counts["schedules"] == 0
    assert store.get("messages", "m1") is not None
    assert virtual_now(store) == datetime(2026, 11, 20, 9, 0, tzinfo=JST)


def test_reset_clears_and_keeps_agent_client_id():
    store = MemoryStore()
    seed_store(store, reset=False, system_now=NOW)
    ts = store.get("team_settings", "ts-integrated_control")
    store.replace("team_settings", ts | {"agent_client_id": "agent-ic"}, etag=ts["_etag"])
    store.create("messages", {"id": "m1", "vehicle_id": "kakuu-suv", "team": "integrated_control"})
    store.create("investigations", {"id": "k1", "vehicle_id": "kakuu-suv"})
    set_virtual_now(store, datetime(2026, 11, 20, 9, 0, tzinfo=JST), NOW)
    counts = seed_store(store, reset=True, system_now=NOW)
    assert counts["artifacts"] == 43
    assert store.get("messages", "m1") is None and store.get("investigations", "k1") is None
    assert store.get("team_settings", "ts-integrated_control")["agent_client_id"] == "agent-ic"
    assert store.get("team_settings", "ts-motor_control").get("agent_client_id") is None
    assert virtual_now(store) == SEED_NOW
