from datetime import datetime

from vehicle_core.constants import JST, Team
from vehicle_core.impact import ImpactResult
from vehicle_core.models import ChangeEvent, Classification, FieldChange, Schedule
from vehicle_core.routing import InvestigationRequest

from proactive_functions.prompts import investigation_prompt

T0 = datetime(2026, 11, 17, 21, 14, tzinfo=JST)
IC, MC = Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL

IMPACT = ImpactResult(
    origin_id="SIG-BrkPedalPos", origin_team=IC, impacted_ids=["SPEC-REGEN-01", "MDL-REGEN", "TC-HILS-031"],
    impacted_by_team={IC: ["SPEC-REGEN-01"], MC: ["MDL-REGEN", "TC-HILS-031"]},
    cross_team_edges=[("SIG-BrkPedalPos", "MDL-REGEN")], highlight_ids=["MDL-REGEN"],
    affects_release_ids=["REL-2026.12"], touches_safety=True,
)

req_s1 = InvestigationRequest(
    id="inv-s1abc", team=MC, trigger="change", origin_artifact_id="SIG-BrkPedalPos",
    source_ids=["chg-001", "chg-002"], impact=IMPACT, matched_watch_ids=["w-1"],
    floor=Classification.NOTIFY_NOW, not_before=T0,
)


def schedule_req(task: str, payload: dict) -> tuple[InvestigationRequest, Schedule]:
    s = Schedule(id="sch-x", team=IC, due_at=T0, task=task, payload=payload)
    r = InvestigationRequest(id="inv-sch", team=IC, trigger="schedule", origin_artifact_id=None, source_ids=[s.id],
                             impact=None, matched_watch_ids=[], floor=Classification.SILENT, not_before=T0)
    return r, s


def test_prompt_mentions_request_ids_and_run_id():
    p = investigation_prompt(req_s1, "run-inv-abc", [])
    for s in [req_s1.id, req_s1.origin_artifact_id, *req_s1.source_ids, "run-inv-abc", req_s1.floor.value]:
        assert s in p


def test_prompt_summarizes_impact_per_team_and_release():
    p = investigation_prompt(req_s1, "run-inv-abc", [])
    assert "motor_control: 2" in p and "integrated_control: 1" in p
    assert "REL-2026.12" in p
    assert "安全" in p


def test_prompt_for_schedule_includes_task_and_payload():
    r, s = schedule_req("release_gap_check", {"release_id": "REL-2026.12"})
    p = investigation_prompt(r, "run-inv-sch", [s])
    assert "release_gap_check" in p and "REL-2026.12" in p


def test_prompt_tells_agent_to_use_get_now():
    assert "get_now" in investigation_prompt(req_s1, "run-inv-abc", [])


def test_prompt_tells_agent_to_finish_run_with_run_id():
    p = investigation_prompt(req_s1, "run-inv-abc", [])
    assert "finish_run" in p and 'run_id="run-inv-abc"' in p


def test_prompt_for_morning_schedule_starts_with_begin_morning_digest():
    r, s = schedule_req("morning_digest", {"recur": "daily"})
    assert "begin_morning_digest" in investigation_prompt(r, "run-inv-sch", [s])
    r2, s2 = schedule_req("release_gap_check", {"release_id": "REL-2026.12"})
    assert "begin_morning_digest" not in investigation_prompt(r2, "run-inv-sch", [s2])


def change(cid: str, path: str, before, after) -> ChangeEvent:
    return ChangeEvent(id=cid, artifact_id="SPEC-BRK-04", changed_by="tanaka", changed_at=T0,
                       changes=[FieldChange(path=path, before=before, after=after)])


def test_prompt_for_change_shows_field_before_and_after():  # シナリオテスト s0: 中身を見ずに知らせていた
    p = investigation_prompt(req_s1, "run-inv-abc", [], [change("chg-001", "attributes.period_ms", 10, 20)])
    assert "attributes.period_ms" in p and "10" in p and "20" in p
    assert "説明文だけ" not in p


def test_prompt_marks_editorial_only_change():
    p = investigation_prompt(req_s1, "run-inv-abc", [], [change("chg-001", "description", "目標原則度", "目標減速度")])
    assert "目標原則度" in p and "目標減速度" in p
    assert "題名や説明文だけの変更" in p
