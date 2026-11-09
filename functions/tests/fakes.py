"""テスト用の偽物（Azure に触れない）。"""


from proactive_functions.memory_store import MemoryStore  # noqa: F401 — テストは tests.fakes から import する
from proactive_functions.store import Conflict, NotFound  # noqa: F401


class RecordingInvoker:
    def __init__(self, fail: bool = False) -> None:
        self.calls = []
        self.fail = fail

    def invoke(self, request) -> None:
        if self.fail:
            raise RuntimeError("エージェントを起動できませんでした")
        self.calls.append(request)


class RecordingPublisher:
    def __init__(self) -> None:
        self.events = []

    def publish(self, team, event: dict) -> None:
        self.events.append((team, event))


class FakeVerifier:
    """「Bearer <client_id>」の client_id をそのまま返す。"""

    def verify(self, authorization):
        from proactive_functions.auth import AuthError
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthError("トークンがありません")
        return authorization.removeprefix("Bearer ")


class InMemoryBackend:
    """MemoryBackend の偽物。scope ごとに項目を持つ。"""

    def __init__(self) -> None:
        self.items: dict[str, list] = {}
        self._n = 0

    def add(self, scope: str, text: str):
        from proactive_functions.mcp.memory import MemoryItem
        self._n += 1
        item = MemoryItem(id=f"{scope}_{self._n}", text=text)
        self.items.setdefault(scope, []).append(item)
        return item

    def search(self, scope: str, query: str | None):
        return [i for i in self.items.get(scope, []) if query is None or query in i.text]

    def delete(self, scope: str, item_id: str) -> bool:
        before = len(self.items.get(scope, []))
        self.items[scope] = [i for i in self.items.get(scope, []) if i.id != item_id]
        return len(self.items[scope]) < before
