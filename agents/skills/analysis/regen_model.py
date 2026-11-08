"""回生協調の簡易モデル（架空）。ブレーキ操作の信号の周期から、回生トルクの立ち上がりの遅れを求める。

モデル:
- ブレーキペダルの踏み込みは、信号の送信周期のどこかの時点で起きる。次の送信まで待ち、受信側はさらに1周期後の制御周期で使う
- 回生トルクは、指令に対して時定数 TAU_MS の一次遅れで立ち上がる
- 遅れは、踏み込みから回生トルクが指令の 50% に達するまでの時間を、踏み込みの時点（周期内の位置）について平均したもの

numpy と scipy だけを使う（作業環境では pip install numpy scipy matplotlib で入れる）。
"""

import numpy as np
from scipy import signal

TAU_MS = 8.0  # 回生トルクの応答の時定数
DT_MS = 0.1
PHASES = 20  # 周期内の踏み込みの位置を何通り試すか


def step_response(signal_period_ms: float, phase_ms: float, t_ms: np.ndarray) -> np.ndarray:
    """踏み込みが周期内の phase_ms の位置で起きたときの、回生トルクの応答（指令に対する割合）。"""
    arrive = (signal_period_ms - phase_ms) + signal_period_ms  # 次の送信まで待ち、さらに1周期後に使う
    u = (t_ms >= arrive).astype(float)
    _, y, _ = signal.lsim(signal.lti([1.0], [TAU_MS, 1.0]), u, t_ms)
    return y


def step_delay_ms(signal_period_ms: float) -> float:
    """踏み込みから回生トルクが 50% に達するまでの平均の遅れ（ms）。"""
    t = np.arange(0.0, 3 * signal_period_ms + 10 * TAU_MS, DT_MS)
    delays = []
    for phase in np.linspace(0.0, signal_period_ms, PHASES, endpoint=False):
        y = step_response(signal_period_ms, phase, t)
        delays.append(t[np.argmax(y >= 0.5)])
    return float(np.mean(delays))


if __name__ == "__main__":
    for period in (10, 20):
        print(f"周期 {period} ms: 遅れ {step_delay_ms(period):.1f} ms")
    print(f"差: {step_delay_ms(20) - step_delay_ms(10):.1f} ms")
