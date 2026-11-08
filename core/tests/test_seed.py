from vehicle_core.constants import Team
from vehicle_core.seed import SEED_NOW, build_dataset


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
