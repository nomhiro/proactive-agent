from vehicle_core.seed import build_dataset

from proactive_web.map_layout import build_map


def _map():
    return build_map(build_dataset().artifacts)


def test_columns_follow_vehicle_domain_requirement_spec_model_test():
    col = {n["id"]: n["column"] for n in _map()["nodes"]}
    assert col["VEHICLE"] == 0 and col["DOMAIN-integrated_control"] == 1
    assert col["REQ-112"] == 2 and col["SR-01"] == 2
    assert col["SPEC-BRK-04"] == 3 and col["SIG-BrkPedalPos"] == 3
    assert col["MDL-RegenCoord"] == 4 and col["TC-HILS-031"] == 5
    assert "R3" not in col and "RV-01" not in col


def test_cross_team_edge_from_signal_to_motor_model():
    edges = {(e["source"], e["target"]): e["cross_team"] for e in _map()["edges"]}
    assert edges[("SIG-BrkPedalPos", "MDL-MotorTq")] is True
    assert edges[("SIG-BrkPedalPos", "MDL-RegenCoord")] is False
    assert edges[("VEHICLE", "DOMAIN-motor_control")] is False
    assert edges[("DOMAIN-integrated_control", "REQ-112")] is False
    assert ("SPEC-BRK-04", "RV-01") not in edges  # レビューは描かない


def test_rows_are_grouped_by_domain_order():
    row = {n["id"]: n["row"] for n in _map()["nodes"] if n["column"] == 5}
    assert row["TC-HILS-031"] < row["TC-HILS-012"]
    assert sorted(row.values()) == list(range(len(row)))


def test_groups_mark_teams_without_assistant():
    m = _map()
    groups = {g["team"]: g["has_assistant"] for g in m["groups"]}
    assert groups["integrated_control"] is True and groups["battery_control"] is False
    assert [g["team"] for g in m["groups"]][:2] == ["integrated_control", "motor_control"]
    group_of = {n["id"]: n["group"] for n in m["nodes"]}
    assert group_of["TC-HILS-031"] == "integrated_control" and group_of["SR-01"] == "functional_safety"
