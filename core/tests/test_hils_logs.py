import csv
import io
from datetime import datetime

from vehicle_core.constants import JST
from vehicle_core.hils_logs import render_hils_log, scenario_log_blobs
from vehicle_core.models import TestRun
from vehicle_core.scenarios import SCENARIOS, StepKind

HEADER = "time_ms,brake_pedal_pos,regen_torque_cmd,regen_torque_act,result"


def s2_run(n: int) -> TestRun:
    steps = SCENARIOS["s2_hils_streak"].steps
    return next(s.test_run for s in steps if s.kind == StepKind.TEST_RUN and s.test_run.id == f"run-s2-{n}")


def passing_run() -> TestRun:
    return TestRun(id="run-pass", testcase_id="TC-HILS-031", feature="regen_coord", result="pass",
                   executed_at=datetime(2026, 11, 16, 10, 0, tzinfo=JST))


def lag_ms(text: str) -> float:
    """指令が初めて 0 を超えた時刻から、実トルクが指令の 63% に初めて達した時刻までの差。"""
    rows = list(csv.DictReader(io.StringIO(text)))
    start = next(r for r in rows if float(r["regen_torque_cmd"]) > 0)
    target = 0.63 * max(float(r["regen_torque_cmd"]) for r in rows)
    reach = next(r for r in rows if float(r["regen_torque_act"]) >= target)
    return float(reach["time_ms"]) - float(start["time_ms"])


def test_hils_log_is_deterministic_and_shaped():
    run = s2_run(1)
    csv1, csv2 = render_hils_log(run), render_hils_log(run)
    assert csv1 == csv2
    lines = csv1.strip().splitlines()
    assert lines[0] == HEADER
    assert len(lines) == 202


def test_failed_run_log_shows_lagging_actual_torque():
    assert lag_ms(render_hils_log(s2_run(1))) >= 15
    assert lag_ms(render_hils_log(passing_run())) < 15


def test_result_column_matches_run():
    rows = list(csv.DictReader(io.StringIO(render_hils_log(s2_run(2)))))
    assert {r["result"] for r in rows} == {"fail"}


def test_scenario_log_blobs_cover_s2_runs():
    blobs = scenario_log_blobs()
    assert {f"hils-logs/TC-HILS-031/s2-{n}.csv" for n in (1, 2, 3)} <= blobs.keys()
    assert all(text.startswith(HEADER) for text in blobs.values())
