from datetime import datetime

from vehicle_core.constants import JST
from vehicle_core.impact import Graph
from vehicle_core.models import Watch
from vehicle_core.notify_policy import decide_delivery
from vehicle_core.release_gaps import release_gaps
from vehicle_core.routing import route_change, route_test_run
from vehicle_core.scenarios import SCENARIO_ORDER, SCENARIOS, StepKind


def test_order_covers_all_scenarios():
    assert set(SCENARIO_ORDER) == set(SCENARIOS)


def test_steps_are_chronological_across_order():
    times = [s.at for sid in SCENARIO_ORDER for s in SCENARIOS[sid].steps]
    assert times == sorted(times)


def test_steps_reference_existing_artifacts_and_people(dataset):
    ids = {a.id for a in dataset.artifacts}
    people = {p.id for p in dataset.people}
    for sc in SCENARIOS.values():
        for st in sc.steps:
            if st.change:
                assert st.change.artifact_id in ids
            if st.test_run:
                assert st.test_run.testcase_id in ids
            if st.person_id:
                assert st.person_id in people


def test_core_expectations_hold_end_to_end(dataset):
    graph = Graph.from_artifacts(dataset.artifacts)
    settings = {s.team: s for s in dataset.team_settings}
    regen_watch = Watch(id="w-regen", team="integrated_control", kind="test_failure_streak",
                        description="回生協調の HILS 失敗", feature="regen_coord", streak=3,
                        delivery="immediate", created_by="tanaka", created_at=datetime(2026, 11, 18, 9, 10, tzinfo=JST))
    runs = list(dataset.test_runs)
    for sid in SCENARIO_ORDER:
        for st in SCENARIOS[sid].steps:
            watches = [regen_watch] if st.expect.get("requires_watch") else []
            if st.kind == StepKind.CHANGE:
                reqs = route_change(st.change, graph, watches)
            elif st.kind == StepKind.TEST_RUN:
                reqs = route_test_run(st.test_run, runs, graph, watches)
                runs.append(st.test_run)
            else:
                reqs = []
            e = st.expect
            if "routed_teams" in e:
                assert [r.team.value for r in reqs] == e["routed_teams"], (sid, st.at)
            if "floor" in e:
                assert reqs[0].floor.value == e["floor"]
            if "impacted_count" in e:
                assert len(reqs[0].impact.impacted_ids) == e["impacted_count"]
            if "deliver_at" in e:
                r = reqs[0]
                d = decide_delivery(r.floor, r.impact.touches_safety, st.at, settings[r.team])
                assert d.deliver_at.isoformat() == e["deliver_at"]
            if "release_id" in e:
                g = release_gaps(dataset, e["release_id"])
                assert (len(g.unverified_requirement_ids), len(g.open_review_ids), len(g.unverified_safety_ids)) \
                    == (e["unverified_requirements"], e["open_reviews"], e["unverified_safety"])


def test_expectations_are_not_vacuous():
    # 通しテストが何も確かめずに通ることがないように、期待値の数を押さえる
    keys = [k for sc in SCENARIOS.values() for st in sc.steps for k in st.expect]
    assert keys.count("routed_teams") == 3
    assert keys.count("floor") == 3
    assert "deliver_at" in keys and "release_id" in keys


def test_change_before_values_match_seed(dataset):
    by_id = {a.id: a for a in dataset.artifacts}
    for sc in SCENARIOS.values():
        for st in sc.steps:
            if not st.change:
                continue
            art = by_id[st.change.artifact_id].model_dump()
            for fc in st.change.changes:
                value = art
                for part in fc.path.split("."):
                    value = value[part]
                assert value == fc.before, (sc.id, fc.path)
