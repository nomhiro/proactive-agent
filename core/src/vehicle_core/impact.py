"""トレーサビリティのリンクを辿って、変更の影響範囲を求める。

リンクの向き: データ X の `links` に Y があるとき、X は Y に依って立つ（Y が上流、X が下流）。
Y が変わると X が影響を受ける。
"""

from collections import deque
from collections.abc import Iterable

from pydantic import BaseModel

from .constants import Team
from .models import Artifact, ArtifactType


class UnknownArtifact(KeyError):
    pass


class Graph:
    def __init__(self, artifacts: dict[str, Artifact]) -> None:
        self._by_id = artifacts
        # 逆引き: ID → その ID を links に持つデータの ID
        self._children: dict[str, set[str]] = {i: set() for i in artifacts}
        for a in artifacts.values():
            for parent in a.links:
                if parent in self._children:
                    self._children[parent].add(a.id)

    @classmethod
    def from_artifacts(cls, artifacts: Iterable[Artifact]) -> "Graph":
        return cls({a.id: a for a in artifacts})

    def get(self, id_: str) -> Artifact:
        try:
            return self._by_id[id_]
        except KeyError:
            raise UnknownArtifact(id_) from None

    def has(self, id_: str) -> bool:
        return id_ in self._by_id

    def parents(self, id_: str) -> list[str]:
        """存在する上流の ID（存在しない ID へのリンクは無視する）。"""
        return [p for p in self.get(id_).links if p in self._by_id]

    def children(self, id_: str) -> set[str]:
        self.get(id_)
        return set(self._children[id_])

    def downstream(self, id_: str) -> set[str]:
        return self._walk(id_, self.children)

    def upstream(self, id_: str) -> set[str]:
        return self._walk(id_, self.parents)

    def _walk(self, start: str, step) -> set[str]:
        self.get(start)
        seen = {start}
        queue = deque([start])
        while queue:
            for nxt in step(queue.popleft()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        seen.discard(start)
        return seen

    def domain_team(self, id_: str) -> Team:
        """影響を受ける領域としてのチーム。テストはリンク先のモデルのチーム（なければ自分のチーム）。"""
        a = self.get(id_)
        if a.type == ArtifactType.TESTCASE:
            for p in self.parents(id_):
                parent = self._by_id[p]
                if parent.type == ArtifactType.MODEL:
                    return parent.team
        return a.team


class ImpactResult(BaseModel):
    origin_id: str
    origin_team: Team
    impacted_ids: list[str]
    impacted_by_team: dict[Team, list[str]]
    cross_team_edges: list[tuple[str, str]]
    highlight_ids: list[str]
    affects_release_ids: list[str]
    touches_safety: bool


def analyze_impact(graph: Graph, origin_id: str) -> ImpactResult:
    origin = graph.get(origin_id)

    # 下流を幅優先で辿り、通ったリンクのうちチームをまたぐものを集める
    seen = {origin_id}
    queue = deque([origin_id])
    cross: set[tuple[str, str]] = set()
    while queue:
        parent = queue.popleft()
        for child in graph.children(parent):
            if graph.domain_team(parent) != graph.domain_team(child):
                cross.add((parent, child))
            if child not in seen:
                seen.add(child)
                queue.append(child)
    impacted = seen - {origin_id}

    by_team: dict[Team, list[str]] = {}
    for i in sorted(impacted):
        by_team.setdefault(graph.domain_team(i), []).append(i)

    releases = set(origin.release_ids)
    for i in impacted:
        releases.update(graph.get(i).release_ids)

    return ImpactResult(
        origin_id=origin_id,
        origin_team=origin.team,
        impacted_ids=sorted(impacted),
        impacted_by_team=by_team,
        cross_team_edges=sorted(cross),
        highlight_ids=sorted(graph.upstream(origin_id) | {origin_id} | impacted),
        affects_release_ids=sorted(releases),
        touches_safety=_touches_safety(graph, {origin_id} | impacted),
    )


def _touches_safety(graph: Graph, ids: set[str]) -> bool:
    for i in ids:
        a = graph.get(i)
        if a.type == ArtifactType.SAFETY_REQUIREMENT:
            return True
        if a.type == ArtifactType.TESTCASE and any(
            graph.get(p).type == ArtifactType.SAFETY_REQUIREMENT for p in graph.parents(i)
        ):
            return True
    return False
