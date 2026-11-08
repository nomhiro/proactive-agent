from datetime import datetime, timedelta

from vehicle_core.constants import JST, Team
from vehicle_core.models import ChangeEvent, Classification, FieldChange, TestRun, Watch
from vehicle_core.routing import coalesce, idempotency_key, route_change, route_test_run


def ev(id_, artifact, minute, path="attributes.period_ms"):
    return ChangeEvent(id=id_, artifact_id=artifact, changed_by="tanaka",
                       changed_at=datetime(2026, 11, 17, 21, minute, tzinfo=JST),
                       changes=[FieldChange(path=path, before=10, after=20)])


def test_signal_change_routes_only_to_owner_team(graph):
    reqs = route_change(ev("e1", "SIG-BrkPedalPos", 10), graph, [])
    assert [r.team for r in reqs] == [Team.INTEGRATED_CONTROL]
    r = reqs[0]
    assert r.floor == Classification.NOTIFY_NOW
    assert len(r.impact.impacted_ids) == 8
    assert r.not_before == datetime(2026, 11, 17, 21, 13, tzinfo=JST)


def test_watching_team_also_receives(graph):
    w = Watch(id="w", team="motor_control", kind="artifact_changed", description="BrkPedalPos",
              target_ids=["SIG-BrkPedalPos"], delivery="digest", created_by="sato",
              created_at=datetime(2026, 11, 1, tzinfo=JST))
    teams = [r.team for r in route_change(ev("e1", "SIG-BrkPedalPos", 10), graph, [w])]
    assert teams == [Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL]


def test_unknown_artifact_routes_nowhere(graph):
    assert route_change(ev("e1", "NOPE-9", 10), graph, []) == []


def test_non_agent_team_artifact_routes_nowhere(graph, dataset):
    battery = next(a for a in dataset.artifacts if a.team == Team.BATTERY_CONTROL)
    assert route_change(ev("e1", battery.id, 10), graph, []) == []


def test_same_event_twice_has_same_key(graph):
    a = route_change(ev("e1", "SIG-BrkPedalPos", 10), graph, [])[0]
    b = route_change(ev("e1", "SIG-BrkPedalPos", 10), graph, [])[0]
    assert a.id == b.id


def test_coalesce_merges_changes_within_window(graph):
    r1 = route_change(ev("e1", "SIG-BrkPedalPos", 10), graph, [])
    r2 = route_change(ev("e2", "SIG-BrkPedalPos", 12), graph, [])
    r3 = route_change(ev("e3", "SIG-BrkPedalPos", 30), graph, [])
    merged = coalesce(r1 + r2 + r3)
    assert sorted(m.source_ids for m in merged) == [["e1", "e2"], ["e3"]]
    first = next(m for m in merged if m.source_ids == ["e1", "e2"])
    assert first.not_before == datetime(2026, 11, 17, 21, 15, tzinfo=JST)
    assert first.id == idempotency_key(Team.INTEGRATED_CONTROL, "change", ["e1", "e2"])


def test_test_run_streak_routes_with_immediate_floor(graph):
    t0 = datetime(2026, 11, 18, 10, 0, tzinfo=JST)
    w = Watch(id="w1", team="integrated_control", kind="test_failure_streak", description="回生協調の HILS 失敗",
              feature="regen_coord", streak=3, delivery="immediate", created_by="tanaka", created_at=t0)
    runs = [TestRun(id=f"r{i}", testcase_id="TC-HILS-031", feature="regen_coord", result="fail",
                    executed_at=t0 + timedelta(hours=3 * i)) for i in range(3)]
    reqs = route_test_run(runs[-1], runs[:-1], graph, [w])
    assert [r.team for r in reqs] == [Team.INTEGRATED_CONTROL]
    assert reqs[0].floor == Classification.NOTIFY_NOW


def test_idempotency_key_ignores_order_and_duplicates():
    k = idempotency_key(Team.EVALUATION, "test_run", ["b", "a", "a"])
    assert k == idempotency_key(Team.EVALUATION, "test_run", ["a", "b"])
    assert len(k) == 32


def test_passing_test_run_without_watch_routes_nowhere(graph):
    run = TestRun(id="p", testcase_id="TC-HILS-031", feature="regen_coord", result="pass",
                  executed_at=datetime(2026, 11, 18, 10, 0, tzinfo=JST))
    assert route_test_run(run, [], graph, []) == []


def test_test_run_for_unknown_testcase_routes_nowhere(graph):
    run = TestRun(id="u", testcase_id="TC-NOPE", feature="x", result="fail",
                  executed_at=datetime(2026, 11, 18, 10, 0, tzinfo=JST))
    assert route_test_run(run, [], graph, []) == []
