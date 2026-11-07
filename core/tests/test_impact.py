from datetime import datetime

import pytest

from vehicle_core.constants import JST, Team
from vehicle_core.impact import Graph, UnknownArtifact, analyze_impact
from vehicle_core.models import Artifact


def test_signal_period_change_impact(graph):
    r = analyze_impact(graph, "SIG-BrkPedalPos")
    assert r.origin_team == Team.INTEGRATED_CONTROL
    assert r.impacted_ids == sorted(["MDL-RegenCoord", "MDL-MotorTq", "TC-HILS-012",
        "TC-HILS-031", "TC-HILS-032", "TC-HILS-033", "TC-HILS-034", "TC-HILS-035"])
    assert r.impacted_by_team[Team.INTEGRATED_CONTROL] == sorted(["MDL-RegenCoord",
        "TC-HILS-031", "TC-HILS-032", "TC-HILS-033", "TC-HILS-034", "TC-HILS-035"])
    assert r.impacted_by_team[Team.MOTOR_CONTROL] == ["MDL-MotorTq", "TC-HILS-012"]
    assert r.cross_team_edges == [("SIG-BrkPedalPos", "MDL-MotorTq")]
    assert {"REQ-112", "SPEC-BRK-04", "SIG-BrkPedalPos"} <= set(r.highlight_ids)
    assert r.affects_release_ids == ["R3"]
    assert r.touches_safety is False


def test_battery_artifacts_not_in_signal_impact(graph, dataset):
    battery_ids = {a.id for a in dataset.artifacts if a.team == Team.BATTERY_CONTROL}
    r = analyze_impact(graph, "SIG-BrkPedalPos")
    assert not battery_ids & set(r.highlight_ids)


def test_unknown_origin_raises(graph):
    with pytest.raises(UnknownArtifact):
        analyze_impact(graph, "NOPE-1")


def test_cycle_terminates():
    t = datetime(2026, 11, 1, tzinfo=JST)
    a = Artifact(id="A", type="spec", team="integrated_control", title="a", owner="x", links=["B"], updated_at=t)
    b = Artifact(id="B", type="spec", team="integrated_control", title="b", owner="x", links=["A"], updated_at=t)
    r = analyze_impact(Graph.from_artifacts([a, b]), "A")
    assert r.impacted_ids == ["B"]


def test_dangling_link_ignored():
    t = datetime(2026, 11, 1, tzinfo=JST)
    a = Artifact(id="A", type="model", team="motor_control", title="a", owner="x", links=["GONE"], updated_at=t)
    g = Graph.from_artifacts([a])
    assert g.upstream("A") == set()


def test_safety_detected_when_impacted_test_links_safety_requirement():
    t = datetime(2026, 11, 1, tzinfo=JST)
    sr = Artifact(id="SR-1", type="safety_requirement", team="functional_safety", title="s", owner="x", updated_at=t)
    m = Artifact(id="M", type="model", team="motor_control", title="m", owner="x", updated_at=t)
    tc = Artifact(id="TC", type="testcase", team="evaluation", title="t", owner="x", links=["M", "SR-1"], updated_at=t)
    assert analyze_impact(Graph.from_artifacts([sr, m, tc]), "M").touches_safety is True


def test_change_to_safety_requirement_itself_touches_safety(graph):
    # 安全要求そのものの変更も「安全要求に関わる」（計画からの補足。台帳の Ruling を参照）
    assert analyze_impact(graph, "SR-04").touches_safety is True
