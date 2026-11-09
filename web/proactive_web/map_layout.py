"""影響マップの配置（決定 13）。左から右へ「車種 → 領域 → 要求 → 仕様・信号 → モデル → テスト」。

ノードの領域は Graph.domain_team（テストはリンク先のモデルのチーム）。リリースとレビューは描かない。
辺の両端の領域が違えば cross_team（画面では、選んだ通知の cross_team_edges だけを赤い点線にする）。
"""

from vehicle_core.constants import AGENT_TEAMS, TEAM_LABELS_JA, Team
from vehicle_core.impact import Graph
from vehicle_core.models import Artifact, ArtifactType

T = ArtifactType
COLUMNS: dict[ArtifactType, int] = {
    T.REQUIREMENT: 2, T.SAFETY_REQUIREMENT: 2, T.SPEC: 3, T.SIGNAL: 3, T.MODEL: 4, T.TESTCASE: 5,
}
DOMAIN_ORDER: list[Team] = [
    Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL, Team.BATTERY_CONTROL, Team.FUNCTIONAL_SAFETY, Team.EVALUATION,
]
VEHICLE_NODE = "VEHICLE"
VEHICLE_LABEL = "架空SUV"


def domain_node(team: Team | str) -> str:
    return f"DOMAIN-{Team(team).value}"


def _order(team: Team) -> int:
    return DOMAIN_ORDER.index(team) if team in DOMAIN_ORDER else len(DOMAIN_ORDER)


def build_map(artifacts: list[Artifact]) -> dict:
    graph = Graph.from_artifacts(artifacts)
    shown = [a for a in artifacts if a.type in COLUMNS]
    group = {a.id: graph.domain_team(a.id) for a in shown}
    teams = sorted(set(group.values()), key=lambda t: (_order(t), t.value))

    nodes = [{"id": VEHICLE_NODE, "label": VEHICLE_LABEL, "type": "vehicle", "column": 0, "row": 0, "group": None}]
    nodes += [{"id": domain_node(t), "label": TEAM_LABELS_JA[t], "type": "domain", "column": 1, "row": i,
               "group": t.value} for i, t in enumerate(teams)]
    for column in sorted(set(COLUMNS.values())):
        in_column = sorted((a for a in shown if COLUMNS[a.type] == column),
                           key=lambda a: (_order(group[a.id]), a.id))
        nodes += [{"id": a.id, "label": a.title, "type": a.type.value, "column": column, "row": row,
                   "group": group[a.id].value} for row, a in enumerate(in_column)]

    ids = {a.id for a in shown}
    edges = [{"source": VEHICLE_NODE, "target": domain_node(t), "cross_team": False} for t in teams]
    edges += [{"source": domain_node(group[a.id]), "target": a.id, "cross_team": False}
              for a in shown if COLUMNS[a.type] == 2]
    edges += [{"source": p, "target": a.id, "cross_team": group[p] != group[a.id]}
              for a in shown for p in a.links if p in ids]
    edges.sort(key=lambda e: (e["source"], e["target"]))

    groups = [{"team": t.value, "label": TEAM_LABELS_JA[t], "has_assistant": t in AGENT_TEAMS} for t in teams]
    return {"nodes": nodes, "edges": edges, "groups": groups}
