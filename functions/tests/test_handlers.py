from datetime import datetime

import pytest
from vehicle_core.constants import JST
from vehicle_core.models import AgentMail, Watch
from vehicle_core.scenarios import SCENARIOS
from vehicle_core.seed import SEED_NOW, build_dataset

from proactive_functions.handlers import handle_agent_mail, handle_change_events, handle_test_runs, mail_request
from tests.fakes import MemoryStore


@pytest.fixture
def store():
    s = MemoryStore()
    ds = build_dataset()
    for a in ds.artifacts:
        s.create("artifacts", a.model_dump(mode="json") | {"origin": "seed"})
    for r in ds.test_runs:
        s.create("test_runs", r.model_dump(mode="json") | {"origin": "seed"})
    return s


S1 = SCENARIOS["s1_signal_period"].steps[0].change.model_dump(mode="json")


def test_signal_change_enqueues_owner_team(store):
    [rid] = handle_change_events([S1], store)
    rec = store.get("investigations", rid)
    assert rec["team"] == "integrated_control" and rec["floor"] == "notify_now"
    assert len(rec["impact"]["impacted_ids"]) == 8


def test_same_batch_twice_makes_one_request(store):  # Review Focus 1
    handle_change_events([S1], store)
    assert handle_change_events([S1], store) == []
    assert len(store.query("investigations")) == 1


def test_seed_docs_are_ignored(store):  # Review Focus 2
    seeded = [r.model_dump(mode="json") | {"origin": "seed"} for r in build_dataset().test_runs]
    assert handle_test_runs(seeded, store) == []
    assert handle_change_events([S1 | {"origin": "seed"}], store) == []
    assert store.query("investigations") == []


def test_broken_doc_is_skipped_and_rest_processed(store):  # Review Focus 5
    broken = {"id": "ce-bad", "vehicle_id": "kakuu-suv", "artifact_id": "SIG-BrkPedalPos"}
    assert len(handle_change_events([broken, S1], store)) == 1


def test_third_hils_failure_with_watch_enqueues(store):
    store.create("watches", Watch(id="w1", team="integrated_control", kind="test_failure_streak",
                                  description="回生協調の HILS", feature="regen_coord", streak=3,
                                  delivery="immediate", created_by="tanaka",
                                  created_at=SEED_NOW).model_dump(mode="json"))
    ids = []
    for st in SCENARIOS["s2_hils_streak"].steps:
        doc = st.test_run.model_dump(mode="json")
        store.create("test_runs", doc)
        ids += handle_test_runs([doc], store)
    last = store.get("investigations", ids[-1])
    assert last["floor"] == "notify_now" and last["matched_watch_ids"] == ["w1"]
    assert [store.get("investigations", i)["floor"] for i in ids[:-1]] == ["silent", "silent"]


def _streak_watch(store, streak: int) -> None:
    store.create("watches", Watch(id=f"w{streak}", team="integrated_control", kind="test_failure_streak",
                                  description="回生協調の HILS", feature="regen_coord", streak=streak,
                                  delivery="immediate", created_by="tanaka",
                                  created_at=SEED_NOW).model_dump(mode="json"))


@pytest.mark.parametrize("streak, fires_on", [(1, "run-s2-1"), (3, "run-s2-3")])
def test_hils_failures_in_one_batch_fire_streak_watch(store, streak, fires_on):
    # シナリオの手順は時計を進めて結果を続けて入れるので、変更フィードには3件まとめて届く。
    # 1件目を判定するとき、後の2件が「より新しい結果」に見えて見張りが鳴らなかった（Azure 上での確認 2回目）
    _streak_watch(store, streak)
    docs = [st.test_run.model_dump(mode="json") for st in SCENARIOS["s2_hils_streak"].steps]
    for doc in docs:
        store.create("test_runs", doc)
    handle_test_runs(docs, store)
    matched = {r["source_ids"][0]: r["matched_watch_ids"] for r in store.query("investigations")}
    assert matched == {d["id"]: ([f"w{streak}"] if d["id"] == fires_on else []) for d in docs}


def test_hils_failure_fires_when_later_run_is_already_stored(store):
    # 2件目が先に書かれ、1件目が別の束で届いても同じ判定になる
    _streak_watch(store, 1)
    first, second = [st.test_run.model_dump(mode="json") for st in SCENARIOS["s2_hils_streak"].steps[:2]]
    store.create("test_runs", first)
    store.create("test_runs", second)
    [rid] = handle_test_runs([first], store)
    assert store.get("investigations", rid)["matched_watch_ids"] == ["w1"]


def test_impact_notice_mail_wakes_recipient_with_notify_now(store):
    mail = AgentMail(id="am-1", thread_id="th-1", from_team="integrated_control", to_team="motor_control",
                     kind="impact_notice", body="MDL-MotorTq に影響", related_artifact_ids=["SIG-BrkPedalPos"],
                     created_at=datetime(2026, 11, 18, 8, 5, tzinfo=JST))
    [rid] = handle_agent_mail([mail.model_dump(mode="json")], store)
    rec = store.get("investigations", rid)
    assert rec["team"] == "motor_control" and rec["trigger"] == "mail" and rec["floor"] == "notify_now"
    assert rec["origin_artifact_id"] == "SIG-BrkPedalPos" and rec["source_ids"] == ["am-1"]


def test_analysis_request_mail_is_silent_floor(store):
    mail = AgentMail(id="am-2", thread_id="th-1", from_team="integrated_control", to_team="evaluation",
                     kind="analysis_request", body="応答の遅れを見て",
                     created_at=datetime(2026, 11, 17, 21, 20, tzinfo=JST))
    [rid] = handle_agent_mail([mail.model_dump(mode="json")], store)
    rec = store.get("investigations", rid)
    assert rec["floor"] == "silent" and rec["origin_artifact_id"] is None


def test_mail_to_team_without_agent_is_ignored():
    mail = AgentMail(id="am-3", thread_id="th-2", from_team="integrated_control", to_team="battery_control",
                     kind="impact_notice", body="x", created_at=datetime(2026, 11, 18, 8, 5, tzinfo=JST))
    assert mail_request(mail) is None


# --- 最終レビューの指摘1: 保存済みの壊れた文書で、以後の処理が止まらない ---

def test_malformed_artifact_does_not_block_routing(store):
    store.create("artifacts", {"id": "BAD", "vehicle_id": "kakuu-suv", "type": "nonsense"})
    assert len(handle_change_events([S1], store)) == 1


def test_malformed_watch_does_not_block_routing(store):
    store.create("watches", {"id": "w-bad", "vehicle_id": "kakuu-suv", "kind": "nonsense"})
    assert len(handle_change_events([S1], store)) == 1


def test_malformed_earlier_run_does_not_block_feature(store):
    store.create("test_runs", {"id": "run-bad", "vehicle_id": "kakuu-suv", "feature": "regen_coord", "result": "maybe"})
    doc = SCENARIOS["s2_hils_streak"].steps[0].test_run.model_dump(mode="json")
    store.create("test_runs", doc)
    assert len(handle_test_runs([doc], store)) == 1
