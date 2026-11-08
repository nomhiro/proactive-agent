import json
from datetime import datetime
from types import SimpleNamespace

from vehicle_core.constants import JST, Team

from proactive_functions.mcp.context import ToolContext
from proactive_functions.mcp.memory import FoundryMemoryBackend
from proactive_functions.mcp.protocol import handle_rpc
from proactive_functions.mcp.server import build_registry
from tests.fakes import InMemoryBackend, MemoryStore

NOW = datetime(2026, 11, 18, 9, 12, tzinfo=JST)
IC, MC = Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL
REGISTRY = build_registry()


def call_raw(memory, name, args=None, team=IC):
    ctx = ToolContext(team=team, store=MemoryStore(), now=NOW, memory=memory)
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}
    return handle_rpc(msg, REGISTRY, ctx)["result"]


def call(memory, name, args=None, team=IC):
    res = call_raw(memory, name, args, team)
    assert res["isError"] is False, res["content"][0]["text"]
    return json.loads(res["content"][0]["text"])


def test_remember_then_recall_in_same_team():
    mem = InMemoryBackend()
    item_id = call(mem, "remember", {"text": "連絡は朝まとめて"})["id"]
    assert [i["id"] for i in call(mem, "recall", {})] == [item_id]
    assert call(mem, "recall", {"query": "朝"})[0]["text"] == "連絡は朝まとめて"


def test_recall_does_not_cross_teams():
    mem = InMemoryBackend()
    call(mem, "remember", {"text": "連絡は朝まとめて"}, team=IC)
    assert call(mem, "recall", {}, team=MC) == []


def test_forget_other_teams_item_returns_false_and_keeps_it():
    mem = InMemoryBackend()
    item_id = call(mem, "remember", {"text": "連絡は朝まとめて"}, team=IC)["id"]
    assert call(mem, "forget", {"item_id": item_id}, team=MC) == {"forgotten": False}
    assert len(call(mem, "recall", {}, team=IC)) == 1


def test_scope_argument_is_ignored():
    mem = InMemoryBackend()
    call(mem, "remember", {"text": "x", "scope": "motor_control"}, team=IC)
    assert call(mem, "recall", {}, team=MC) == []
    assert len(call(mem, "recall", {}, team=IC)) == 1


def test_forget_removes_item_from_recall():  # 設計書 7.7 節「確実に消える」
    mem = InMemoryBackend()
    item_id = call(mem, "remember", {"text": "連絡は朝まとめて"})["id"]
    assert call(mem, "forget", {"item_id": item_id}) == {"forgotten": True}
    assert call(mem, "recall", {}) == []


def test_memory_not_configured_is_is_error():
    assert call_raw(None, "recall", {})["isError"] is True


# --- FoundryMemoryBackend（SDK の呼び出しを偽物で受ける） -----------------------

class FakeMemoryStores:
    def __init__(self):
        self.calls = []
        self.items = {}  # memory_id -> (scope, content)

    def create_memory(self, *, name, scope, content, kind):
        self.calls.append(("create_memory", name, scope, kind))
        mid = f"{scope}_{len(self.items) + 1}"
        self.items[mid] = (scope, content)
        return SimpleNamespace(memory_id=mid, content=content)

    def list_memories(self, *, name, scope):
        self.calls.append(("list_memories", name, scope))
        return [SimpleNamespace(memory_id=k, content=v[1]) for k, v in self.items.items() if v[0] == scope]

    def search_memories(self, *, name, scope, items, options):
        self.calls.append(("search_memories", name, scope))
        return SimpleNamespace(memories=[SimpleNamespace(memory_item=m) for m in self.list_memories(name=name, scope=scope)])

    def delete_memory(self, *, name, memory_id):
        self.calls.append(("delete_memory", name, memory_id))
        self.items.pop(memory_id)


def foundry_backend():
    stores = FakeMemoryStores()
    project = SimpleNamespace(beta=SimpleNamespace(memory_stores=stores))
    return FoundryMemoryBackend(project, "team-memory"), stores


def test_foundry_backend_passes_scope_and_store_name():
    backend, stores = foundry_backend()
    item = backend.add("integrated_control", "連絡は朝まとめて")
    assert stores.calls[0] == ("create_memory", "team-memory", "integrated_control", "user_profile")
    assert [i.id for i in backend.search("integrated_control", None)] == [item.id]
    assert [i.id for i in backend.search("integrated_control", "朝")] == [item.id]
    assert backend.search("motor_control", None) == []


def test_foundry_backend_delete_checks_scope_before_deleting():
    # Memory ストアの削除は項目 ID だけで通るので、先にその scope の項目かを確かめる（再検討案 9.2 節）
    backend, stores = foundry_backend()
    item = backend.add("integrated_control", "x")
    assert backend.delete("motor_control", item.id) is False
    assert not any(c[0] == "delete_memory" for c in stores.calls)
    assert backend.delete("integrated_control", item.id) is True
    assert ("delete_memory", "team-memory", item.id) in stores.calls
