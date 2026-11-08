"""チームの記憶の道具（設計書 7.7 節）。Foundry Memory の Memory ストアを、scope＝チームで使う。

harness 付きエージェントは Memory を直接使えないので、MCP サーバーが API を呼ぶ。
scope は呼び出し元のチーム（トークンから決めたもの）だけ。エージェントに scope を選ばせない。
"""

from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

from .context import ToolContext, ToolError
from .protocol import Registry, Tool

SEARCH_MAX = 20


class MemoryItem(BaseModel):
    id: str
    text: str
    created_at: AwareDatetime | None = None


class MemoryBackend(Protocol):
    def add(self, scope: str, text: str) -> MemoryItem: ...
    def search(self, scope: str, query: str | None) -> list[MemoryItem]: ...
    def delete(self, scope: str, item_id: str) -> bool: ...


def _item(obj) -> MemoryItem:
    inner = getattr(obj, "memory_item", obj)
    return MemoryItem(id=inner.memory_id, text=inner.content)


class FoundryMemoryBackend:
    """project.beta.memory_stores を使う（azure-ai-projects 2.10、再検討案 9.2 節で確かめた呼び方）。"""

    def __init__(self, project, store_name: str) -> None:
        self._stores = project.beta.memory_stores
        self._name = store_name

    def add(self, scope: str, text: str) -> MemoryItem:
        created = self._stores.create_memory(name=self._name, scope=scope, content=text, kind="user_profile")
        return MemoryItem(id=created.memory_id, text=created.content)

    def search(self, scope: str, query: str | None) -> list[MemoryItem]:
        if not query:
            return [_item(m) for m in self._stores.list_memories(name=self._name, scope=scope)]
        from azure.ai.projects.models import MemorySearchOptions
        res = self._stores.search_memories(
            name=self._name, scope=scope, items=[{"role": "user", "content": query, "type": "message"}],
            options=MemorySearchOptions(max_memories=SEARCH_MAX))
        return [_item(m) for m in res.memories]

    def delete(self, scope: str, item_id: str) -> bool:
        # 削除は項目 ID だけで通ってしまうので、その scope の項目かを先に確かめる
        if not any(i.id == item_id for i in self.search(scope, None)):
            return False
        self._stores.delete_memory(name=self._name, memory_id=item_id)
        return True


class _Args(BaseModel):
    model_config = ConfigDict(extra="ignore")  # scope などは捨てる


class RememberArgs(_Args):
    text: str


class RecallArgs(_Args):
    query: str | None = None


class ForgetArgs(_Args):
    item_id: str


def _memory(ctx: ToolContext) -> MemoryBackend:
    if ctx.memory is None:
        raise ToolError("記憶の仕組みが設定されていません")
    return ctx.memory


def remember(ctx: ToolContext, args: dict) -> dict:
    a = RememberArgs.model_validate(args)
    return {"id": _memory(ctx).add(ctx.team.value, a.text).id}


def recall(ctx: ToolContext, args: dict) -> list[dict]:
    a = RecallArgs.model_validate(args)
    return [i.model_dump(mode="json") for i in _memory(ctx).search(ctx.team.value, a.query)]


def forget(ctx: ToolContext, args: dict) -> dict:
    a = ForgetArgs.model_validate(args)
    return {"forgotten": _memory(ctx).delete(ctx.team.value, a.item_id)}


_S = {"type": "string"}

TOOLS = [
    Tool("remember", "チームの好みや、覚えてほしいと頼まれたことを覚える（例: 「連絡は朝まとめて」）。見張りの条件は add_watch を使う。",
         {"type": "object", "properties": {"text": _S}, "required": ["text"]}, remember),
    Tool("recall", "チームについて覚えていることを返す。query を渡すと関係するものを探す。知らせ方を決める前に確かめる。",
         {"type": "object", "properties": {"query": _S}, "required": []}, recall),
    Tool("forget", "覚えていることを1件忘れる（「忘れて」と頼まれたとき）。item_id は recall で得る。",
         {"type": "object", "properties": {"item_id": _S}, "required": ["item_id"]}, forget),
]


def register_memory_tools(registry: Registry) -> None:
    for t in TOOLS:
        registry.add(t)
