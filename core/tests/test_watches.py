from datetime import datetime, timedelta

from vehicle_core.constants import JST
from vehicle_core.impact import analyze_impact
from vehicle_core.models import TestRun, Watch
from vehicle_core.watches import failure_streak, match_change_watches, match_test_watches

T0 = datetime(2026, 11, 18, 10, 0, tzinfo=JST)


def _run(i, result, hours):
    return TestRun(id=f"r{i}", testcase_id="TC-HILS-031", feature="regen_coord",
                   result=result, executed_at=T0 + timedelta(hours=hours))


REGEN_WATCH = Watch(id="w1", team="integrated_control", kind="test_failure_streak",
                    description="回生協調の HILS 失敗", feature="regen_coord", streak=3,
                    delivery="immediate", created_by="tanaka", created_at=T0)


def test_failure_streak_counts_trailing_fails():
    runs = [_run(0, "pass", 0), _run(1, "fail", 1), _run(2, "fail", 2)]
    assert failure_streak(runs, "regen_coord") == 2


def test_watch_fires_exactly_on_third_failure():
    runs = [_run(0, "pass", 0), _run(1, "fail", 1), _run(2, "fail", 2)]
    third = _run(3, "fail", 3)
    assert match_test_watches([REGEN_WATCH], runs, third) == [REGEN_WATCH]


def test_watch_does_not_refire_on_fourth_failure():
    runs = [_run(i, "fail", i) for i in range(1, 4)]
    assert match_test_watches([REGEN_WATCH], runs, _run(4, "fail", 4)) == []


def test_watch_ignores_other_feature():
    other = TestRun(id="o", testcase_id="TC-HILS-012", feature="motor_torque", result="fail", executed_at=T0)
    assert match_test_watches([REGEN_WATCH], [], other) == []


def test_change_watch_matches_impacted_target(graph):
    w = Watch(id="w2", team="integrated_control", kind="artifact_changed", description="BrkPedalPos を使う全モデル",
              target_ids=["MDL-MotorTq"], delivery="digest", created_by="tanaka", created_at=T0)
    assert match_change_watches([w], analyze_impact(graph, "SIG-BrkPedalPos")) == [w]


def test_streak_is_same_whether_runs_include_new_run():
    runs = [_run(0, "pass", 0), _run(1, "fail", 1), _run(2, "fail", 2)]
    third = _run(3, "fail", 3)
    assert match_test_watches([REGEN_WATCH], runs + [third], third) == [REGEN_WATCH]


def test_late_arriving_older_run_does_not_refire():
    runs = [_run(0, "pass", 0), _run(1, "fail", 1), _run(2, "fail", 2), _run(3, "fail", 3)]
    late = _run(9, "pass", -1)  # 遅れて届いた古い結果
    assert match_test_watches([REGEN_WATCH], runs, late) == []


def test_watch_streak_must_be_positive():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        REGEN_WATCH.model_validate(REGEN_WATCH.model_dump() | {"streak": 0})
