import uuid

from vehicle_core.constants import VEHICLE_ID, Team

from proactive_deploy.setup import sync_agent_client_ids


class DictStore:
    """Store の必要な分だけ（get / query / replace / create）。"""

    def __init__(self, docs):
        self.docs = {d["id"]: d | {"_etag": uuid.uuid4().hex} for d in docs}
        self.replaced = []

    def get(self, container, id):
        return self.docs.get(id)

    def query(self, container, where=None):
        return [d for d in self.docs.values() if all(d.get(k) == v for k, v in (where or {}).items())]

    def replace(self, container, doc, *, etag):
        assert self.docs[doc["id"]]["_etag"] == etag
        self.docs[doc["id"]] = doc | {"_etag": uuid.uuid4().hex}
        self.replaced.append(doc["id"])
        return self.docs[doc["id"]]

    def create(self, container, doc):
        self.docs[doc["id"]] = doc | {"_etag": uuid.uuid4().hex}
        return self.docs[doc["id"]]


def ts(team, client_id=None, **extra):
    return {"id": f"ts-{team}", "vehicle_id": VEHICLE_ID, "team": team, "proactivity": "normal",
            "quiet_start": "20:00:00", "quiet_end": "07:59:00", "members": [{"id": "p1"}],
            "agent_client_id": client_id, **extra}


def test_sync_agent_client_ids_updates_only_changed_teams_and_keeps_other_fields():
    store = DictStore([ts("integrated_control", "old-ic"), ts("motor_control", "c-mc"), ts("evaluation"),
                       ts("chief_engineer", "old-ce")])
    changed = sync_agent_client_ids(store, {Team.INTEGRATED_CONTROL: "c-ic", Team.MOTOR_CONTROL: "c-mc",
                                            Team.EVALUATION: "c-ev", Team.CHIEF_ENGINEER: "c-ce"})
    assert sorted(changed) == ["chief_engineer", "evaluation", "integrated_control"]
    assert store.replaced.count("ts-motor_control") == 0
    doc = store.get("team_settings", "ts-integrated_control")
    assert doc["agent_client_id"] == "c-ic" and doc["members"] == [{"id": "p1"}]


def test_sync_agent_client_ids_creates_missing_team_settings():
    store = DictStore([])
    assert sync_agent_client_ids(store, {Team.EVALUATION: "c-ev"}) == ["evaluation"]
    assert store.get("team_settings", "ts-evaluation")["agent_client_id"] == "c-ev"


class FakeStores:
    def __init__(self, get_error):
        self.get_error = get_error
        self.created = []

    def get(self, name):
        raise self.get_error

    def create(self, **kwargs):
        self.created.append(kwargs["name"])


def test_ensure_memory_store_creates_only_when_missing():  # 最終レビューの M6
    from types import SimpleNamespace

    import pytest
    from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

    from proactive_deploy.setup import ensure_memory_store
    missing = FakeStores(ResourceNotFoundError("not found"))
    assert ensure_memory_store(SimpleNamespace(beta=SimpleNamespace(memory_stores=missing)), "m", "c", "e") == "created"
    assert missing.created == ["m"]
    forbidden = FakeStores(HttpResponseError(message="Forbidden"))
    with pytest.raises(HttpResponseError):
        ensure_memory_store(SimpleNamespace(beta=SimpleNamespace(memory_stores=forbidden)), "m", "c", "e")
    assert forbidden.created == []
