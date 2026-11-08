"""架空の HILS ログ（CSV）。同じ試験結果からは、いつも同じログを作る（乱数を使わない）。

ブレーキペダルを 200ms で踏み込み、回生トルクの指令が階段状に立ち上がる。実トルクは一次遅れで追従する。
失敗した試験は、むだ時間と時定数が大きく、指令から実トルクの立ち上がりが 15ms 以上遅れる（シナリオ2の筋書き）。
"""

import math

from .models import TestRun
from .scenarios import SCENARIOS, StepKind

HEADER = "time_ms,brake_pedal_pos,regen_torque_cmd,regen_torque_act,result"
STEP_MS = 10
END_MS = 2000
PEDAL_ON_MS = 200
TORQUE_CMD_NM = 120.0
# (むだ時間 ms, 時定数 ms)
PASS_DYNAMICS = (0.0, 8.0)
FAIL_DYNAMICS = (10.0, 18.0)


def _actual(t_ms: float, start_ms: float, dead_ms: float, tau_ms: float) -> float:
    elapsed = t_ms - start_ms - dead_ms
    if elapsed <= 0:
        return 0.0
    return TORQUE_CMD_NM * (1 - math.exp(-elapsed / tau_ms))


def render_hils_log(run: TestRun) -> str:
    dead, tau = FAIL_DYNAMICS if run.result == "fail" else PASS_DYNAMICS
    lines = [HEADER]
    for t in range(0, END_MS + 1, STEP_MS):
        pedal = 0.35 if t >= PEDAL_ON_MS else 0.0
        cmd = TORQUE_CMD_NM if t >= PEDAL_ON_MS else 0.0
        act = _actual(t, PEDAL_ON_MS, dead, tau) if t >= PEDAL_ON_MS else 0.0
        lines.append(f"{t},{pedal:.2f},{cmd:.1f},{act:.1f},{run.result}")
    return "\n".join(lines) + "\n"


def scenario_log_blobs() -> dict[str, str]:
    """シナリオに出てくる試験結果のうち log_blob を持つものについて、log_blob → CSV。"""
    out = {}
    for scenario in SCENARIOS.values():
        for step in scenario.steps:
            if step.kind == StepKind.TEST_RUN and step.test_run and step.test_run.log_blob:
                out[step.test_run.log_blob] = render_hils_log(step.test_run)
    return out
