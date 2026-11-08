"""テスト用の偽物（Azure に触れない）。"""

import copy
import itertools
from typing import Any

from proactive_functions.store import Conflict, NotFound


class MemoryStore:
    """Store の偽物。`_etag` は書くたびに変わる。

    競合を作るためのつまみ: before_replace（置き換えの直前に呼ぶ）と touch（etag だけ変える）。
    """

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {}
        self._seq = itertools.count(1)
        self.before_replace = None

    def touch(self, container: str, id: str) -> None:
        self._put(container, self._box(container)[id])

    def _box(self, container: str) -> dict[str, dict]:
        return self._data.setdefault(container, {})

    def _put(self, container: str, doc: dict) -> dict:
        assert doc.get("vehicle_id"), "すべての文書は vehicle_id を持つ"
        saved = copy.deepcopy(doc)
        saved["_etag"] = f'"{next(self._seq)}"'
        self._box(container)[saved["id"]] = saved
        return copy.deepcopy(saved)

    def get(self, container: str, id: str) -> dict | None:
        d = self._box(container).get(id)
        return copy.deepcopy(d) if d else None

    def create(self, container: str, doc: dict) -> dict:
        if doc["id"] in self._box(container):
            raise Conflict(doc["id"])
        return self._put(container, doc)

    def upsert(self, container: str, doc: dict) -> dict:
        return self._put(container, doc)

    def replace(self, container: str, doc: dict, *, etag: str) -> dict:
        if self.before_replace:
            self.before_replace(container, doc)
        cur = self._box(container).get(doc["id"])
        if cur is None:
            raise NotFound(doc["id"])
        if cur["_etag"] != etag:
            raise Conflict(doc["id"])
        return self._put(container, doc)

    def delete(self, container: str, id: str) -> None:
        if self._box(container).pop(id, None) is None:
            raise NotFound(id)

    def query(self, container: str, where: dict[str, Any] | None = None) -> list[dict]:
        def match(d: dict) -> bool:
            return all((d.get(k) is None) if v is None else d.get(k) == v for k, v in (where or {}).items())
        return [copy.deepcopy(d) for d in self._box(container).values() if match(d)]



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
