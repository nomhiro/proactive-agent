from datetime import datetime, timedelta

from vehicle_core.constants import JST
from vehicle_core.models import TestRun
from vehicle_core.release_gaps import latest_result, release_gaps
from vehicle_core.seed import SEED_NOW


def test_r3_gap_counts_match_mockup(dataset):
    r = release_gaps(dataset, "R3")
    assert len(r.unverified_requirement_ids) == 7
    assert len(r.open_review_ids) == 3
    assert len(r.unverified_safety_ids) == 2


def test_latest_result_uses_newest_run():
    t = datetime(2026, 11, 1, tzinfo=JST)
    runs = [TestRun(id="1", testcase_id="TC", feature="f", result="fail", executed_at=t),
            TestRun(id="2", testcase_id="TC", feature="f", result="pass", executed_at=t + timedelta(hours=1))]
    assert latest_result(runs, "TC") == "pass"
    assert latest_result(runs, "OTHER") is None


def test_requirement_with_failing_latest_run_is_unverified(dataset):
    # REQ-112 は R3 対象。TC-HILS-031..035 の最新がすべて fail になるようにすると未検証になる
    t = SEED_NOW + timedelta(hours=1)
    fails = [TestRun(id=f"x{i}", testcase_id=f"TC-HILS-03{i}", feature="regen_coord", result="fail", executed_at=t)
             for i in range(1, 6)]
    ds = dataset.model_copy(update={"test_runs": dataset.test_runs + fails})
    assert "REQ-112" in release_gaps(ds, "R3").unverified_requirement_ids
