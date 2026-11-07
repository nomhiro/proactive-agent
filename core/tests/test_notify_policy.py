from datetime import datetime, time, timezone

import pytest

from vehicle_core.constants import JST
from vehicle_core.impact import analyze_impact
from vehicle_core.models import Classification, Proactivity, TeamSettings
from vehicle_core.notify_policy import (
    decide_delivery,
    final_classification,
    floor_classification,
    is_quiet,
    next_time_at,
)

S = TeamSettings(id="ts-ic", team="integrated_control")


def at(d, h, m=0, s=0):
    return datetime(2026, 11, d, h, m, s, tzinfo=JST)


def test_release_impact_is_notify_now_but_deferred_at_night(graph):
    impact = analyze_impact(graph, "SIG-BrkPedalPos")
    floor = floor_classification(impact, substantive=True, matched=[])
    assert floor == Classification.NOTIFY_NOW
    d = decide_delivery(floor, impact.touches_safety, at(17, 21, 10), S)
    assert d.mode == "immediate" and d.deliver_at == at(18, 8, 0)


def test_editorial_change_floor_is_silent(graph):
    impact = analyze_impact(graph, "SPEC-BRK-04")
    assert floor_classification(impact, substantive=False, matched=[]) == Classification.SILENT


def test_safety_is_immediate_even_at_night_and_when_off():
    off = S.model_copy(update={"proactivity": Proactivity.OFF})
    d = decide_delivery(Classification.NOTIFY_NOW, True, at(17, 23, 0), off)
    assert d.mode == "immediate" and d.deliver_at == at(17, 23, 0)


def test_quiet_boundaries():
    assert is_quiet(at(17, 20, 0, 0), S) is True
    assert is_quiet(at(17, 19, 59, 59), S) is False
    assert is_quiet(at(18, 7, 59, 59), S) is True
    assert is_quiet(at(18, 8, 0, 0), S) is False


def test_digest_goes_to_next_8am():
    assert decide_delivery(Classification.DIGEST, False, at(18, 14, 0), S).deliver_at == at(19, 8, 0)
    assert decide_delivery(Classification.DIGEST, False, at(18, 7, 0), S).deliver_at == at(18, 8, 0)


def test_proactivity_levels():
    imp = S.model_copy(update={"proactivity": Proactivity.IMPORTANT_ONLY})
    freq = S.model_copy(update={"proactivity": Proactivity.FREQUENT})
    assert decide_delivery(Classification.DIGEST, False, at(18, 14, 0), imp).mode == "none"
    d = decide_delivery(Classification.DIGEST, False, at(18, 14, 0), freq)
    assert d.mode == "immediate" and d.deliver_at == at(18, 14, 0)


def test_llm_cannot_lower_floor():
    assert final_classification(Classification.NOTIFY_NOW, Classification.SILENT) == Classification.NOTIFY_NOW
    assert final_classification(Classification.SILENT, Classification.DIGEST) == Classification.DIGEST


def test_utc_input_is_converted():
    utc_2110_jst = datetime(2026, 11, 17, 12, 10, tzinfo=timezone.utc)
    assert decide_delivery(Classification.NOTIFY_NOW, False, utc_2110_jst, S).deliver_at == at(18, 8, 0)


def test_naive_now_is_rejected():
    with pytest.raises(ValueError):
        decide_delivery(Classification.NOTIFY_NOW, False, datetime(2026, 11, 17, 21, 10), S)


def test_next_time_at_exact_time_returns_now():
    assert next_time_at(at(18, 8, 0), time(8, 0)) == at(18, 8, 0)


def test_quiet_window_that_does_not_cross_midnight():
    lunch = S.model_copy(update={"quiet_start": time(12, 0), "quiet_end": time(13, 0)})
    assert is_quiet(at(18, 12, 30), lunch) is True
    assert is_quiet(at(18, 21, 0), lunch) is False


def test_editorial_change_near_safety_is_not_delivered():
    # 安全要求の近くでも、誤字の修正（silent）は夜中に届けない
    assert decide_delivery(Classification.SILENT, True, at(17, 23, 0), S).mode == "none"
