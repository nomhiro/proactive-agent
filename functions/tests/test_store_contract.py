"""Store の契約。MemoryStore と、環境変数 COSMOS_TEST_ENDPOINT があれば CosmosStore でも確かめる。"""

import os

import pytest

from proactive_functions.store import Conflict, NotFound
from tests.fakes import MemoryStore


def _stores():
    yield pytest.param(lambda: MemoryStore(), id="memory")
    if os.environ.get("COSMOS_TEST_ENDPOINT"):
        def cosmos():
            from azure.identity import DefaultAzureCredential

            from proactive_functions.store import CosmosStore
            return CosmosStore(os.environ["COSMOS_TEST_ENDPOINT"], "proactive", DefaultAzureCredential())
        yield pytest.param(cosmos, id="cosmos")


@pytest.fixture(params=list(_stores()))
def store(request):
    return request.param()


def doc(id_, **kw):
    return {"id": id_, "vehicle_id": "kakuu-suv", **kw}


def test_create_twice_conflicts(store):
    store.create("investigations", doc("t-c1"))
    try:
        with pytest.raises(Conflict):
            store.create("investigations", doc("t-c1"))
    finally:
        store.delete("investigations", "t-c1")


def test_created_doc_has_etag_and_get_returns_it(store):
    created = store.create("investigations", doc("t-g1", status="pending"))
    try:
        assert created["_etag"]
        got = store.get("investigations", "t-g1")
        assert got["status"] == "pending" and got["_etag"] == created["_etag"]
    finally:
        store.delete("investigations", "t-g1")


def test_replace_with_stale_etag_conflicts(store):
    first = store.create("investigations", doc("t-r1", status="pending"))
    try:
        second = store.replace("investigations", {**first, "status": "dispatched"}, etag=first["_etag"])
        assert second["status"] == "dispatched" and second["_etag"] != first["_etag"]
        with pytest.raises(Conflict):
            store.replace("investigations", {**first, "status": "merged"}, etag=first["_etag"])
    finally:
        store.delete("investigations", "t-r1")


def test_replace_missing_raises_not_found(store):
    with pytest.raises(NotFound):
        store.replace("investigations", doc("t-none"), etag='"x"')


def test_upsert_overwrites(store):
    store.upsert("investigations", doc("t-u1", status="a"))
    try:
        store.upsert("investigations", doc("t-u1", status="b"))
        assert store.get("investigations", "t-u1")["status"] == "b"
    finally:
        store.delete("investigations", "t-u1")


def test_query_equality_and_none(store):
    store.create("notifications", doc("t-q1", team="evaluation", delivered_at=None))
    store.create("notifications", doc("t-q2", team="evaluation"))
    store.create("notifications", doc("t-q3", team="evaluation", delivered_at="2026-11-18T08:00:00+09:00"))
    store.create("notifications", doc("t-q4", team="motor_control"))
    try:
        ids = {d["id"] for d in store.query("notifications", {"delivered_at": None, "team": "evaluation"})}
        assert {"t-q1", "t-q2"} <= ids and not ids & {"t-q3", "t-q4"}
        everything = {d["id"] for d in store.query("notifications")}
        assert {"t-q1", "t-q2", "t-q3", "t-q4"} <= everything
    finally:
        for i in ("t-q1", "t-q2", "t-q3", "t-q4"):
            store.delete("notifications", i)


def test_get_missing_returns_none_and_delete_missing_raises(store):
    assert store.get("investigations", "t-none") is None
    with pytest.raises(NotFound):
        store.delete("investigations", "t-none")


def test_build_query_none_and_params():
    from proactive_functions.store import build_query
    sql, params = build_query({"status": "pending", "delivered_at": None})
    assert sql == ("SELECT * FROM c WHERE c.status = @p0 AND "
                   "(NOT IS_DEFINED(c.delivered_at) OR IS_NULL(c.delivered_at))")
    assert params == [{"name": "@p0", "value": "pending"}]
    assert build_query(None) == ("SELECT * FROM c", [])


def test_build_query_rejects_unsafe_field():
    from proactive_functions.store import build_query
    with pytest.raises(ValueError):
        build_query({"x OR 1=1 --": 1})
