from datetime import datetime

from vehicle_core.constants import JST, Team
from vehicle_core.seed import SEED_NOW, build_dataset, build_schedules


def test_build_dataset_is_deterministic():
    assert build_dataset() == build_dataset()


def test_all_links_resolve(dataset):
    ids = {a.id for a in dataset.artifacts}
    for a in dataset.artifacts:
        assert set(a.links) <= ids, a.id
        assert set(a.release_ids) <= ids, a.id


def test_ids_are_unique(dataset):
    ids = [a.id for a in dataset.artifacts]
    assert len(ids) == len(set(ids))


def test_scenario_critical_values(dataset):
    by_id = {a.id: a for a in dataset.artifacts}
    assert by_id["SIG-BrkPedalPos"].attributes["period_ms"] == 10
    assert by_id["MDL-RegenCoord"].version == "1.8"
    assert by_id["MDL-MotorTq"].team == Team.MOTOR_CONTROL
    assert by_id["R3"].attributes["due_date"] == "2026-11-30"


def test_core_people_exist(dataset):
    assert {"tanaka", "sato", "suzuki", "takahashi"} <= {p.id for p in dataset.people}


def test_seed_timestamps_before_seed_now(dataset):
    assert all(a.updated_at <= SEED_NOW for a in dataset.artifacts)
    assert all(r.executed_at <= SEED_NOW for r in dataset.test_runs)


def test_no_real_company_names(dataset):
    banned = ["トヨタ", "ホンダ", "日産", "Toyota", "Honda", "Nissan", "Denso", "デンソー"]
    text = dataset.model_dump_json()
    assert not any(b in text for b in banned)


def test_schedules_keep_only_release_gap_check(dataset):
    # 朝のまとめとブリーフィングは Foundry Routines が起動する（Plan 3 決定 16）
    sch = {s.id: s for s in build_schedules(dataset)}
    assert {s.task for s in sch.values()} == {"release_gap_check"}
    gap = sch["sch-release-gap-R3"]
    assert gap.team == Team.CHIEF_ENGINEER and gap.due_at == datetime(2026, 11, 23, 8, 0, tzinfo=JST)
    assert gap.payload == {"release_id": "R3"}
    assert all(s.done_at is None for s in sch.values())
