"""デモのシナリオ（設計書 5.3 節）。日時は仮想の時計の値。

`expect` はコアだけで確かめられる期待値。エージェントの振る舞い（承認カード、返事、
エスカレーション）の期待値は Plan 4 のシナリオテストで扱う。
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel

from .constants import JST, Team
from .models import ChangeEvent, FieldChange, TestRun


class StepKind(StrEnum):
    SET_CLOCK = "set_clock"
    CHANGE = "change"
    TEST_RUN = "test_run"
    HUMAN_SAYS = "human_says"
    APPROVE = "approve"


class ScenarioStep(BaseModel):
    kind: StepKind
    at: AwareDatetime
    change: ChangeEvent | None = None
    test_run: TestRun | None = None
    team: Team | None = None
    person_id: str | None = None
    text: str | None = None
    expect: dict[str, Any] = {}


class Scenario(BaseModel):
    id: str
    title_ja: str
    steps: list[ScenarioStep]


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=JST)


def _clock(at: datetime, **expect: Any) -> ScenarioStep:
    return ScenarioStep(kind=StepKind.SET_CLOCK, at=at, expect=expect)


def _says(at: datetime, team: Team, person_id: str, text: str) -> ScenarioStep:
    return ScenarioStep(kind=StepKind.HUMAN_SAYS, at=at, team=team, person_id=person_id, text=text)


def _approve(at: datetime, team: Team, person_id: str) -> ScenarioStep:
    """そのチームの承認待ちの影響の連絡（impact_notice）のうち、最も古いものを人が送る。"""
    return ScenarioStep(kind=StepKind.APPROVE, at=at, team=team, person_id=person_id)


def _change(id_: str, at: datetime, artifact_id: str, path: str, before: Any, after: Any,
            expect: dict[str, Any]) -> ScenarioStep:
    event = ChangeEvent(id=id_, artifact_id=artifact_id, changed_by="tanaka", changed_at=at,
                        changes=[FieldChange(path=path, before=before, after=after)])
    return ScenarioStep(kind=StepKind.CHANGE, at=at, change=event, expect=expect)


def _hils_fail(n: int, at: datetime, expect: dict[str, Any] | None = None) -> ScenarioStep:
    run = TestRun(id=f"run-s2-{n}", testcase_id="TC-HILS-031", feature="regen_coord", result="fail",
                  executed_at=at, log_blob=f"hils-logs/TC-HILS-031/s2-{n}.csv")
    return ScenarioStep(kind=StepKind.TEST_RUN, at=at, test_run=run, expect=expect or {})


IC, MC = Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL

SCENARIOS: dict[str, Scenario] = {
    "s1_signal_period": Scenario(id="s1_signal_period", title_ja="CAN 信号の周期変更", steps=[
        _change("ce-s1-1", _at(17, 21, 10), "SIG-BrkPedalPos", "attributes.period_ms", 10, 20, {
            "routed_teams": ["integrated_control"],
            "impacted_count": 8,
            "floor": "notify_now",
            "deliver_at": "2026-11-18T08:00:00+09:00",
        }),
        _clock(_at(18, 8, 0)),
        _approve(_at(18, 8, 20), IC, "tanaka"),
        _says(_at(18, 8, 40), MC, "sato", "今週は v2.1 で手一杯で、R3 までに 20ms 対応は無理です"),
        _says(_at(18, 8, 50), IC, "tanaka", "周期は CAN 負荷の都合で戻せません"),
    ]),
    "s5_watch_memory": Scenario(id="s5_watch_memory", title_ja="会話で見張りを頼む・忘れさせる", steps=[
        _says(_at(18, 9, 10), IC, "tanaka", "回生協調の HILS が落ちたら、今後は朝を待たずにすぐ教えて"),
        _says(_at(18, 9, 12), IC, "tanaka", "連絡は朝まとめて"),
        _says(_at(18, 9, 15), IC, "tanaka", "さっきの『朝まとめて』は忘れて"),
    ]),
    "s2_hils_streak": Scenario(id="s2_hils_streak", title_ja="HILS の失敗傾向", steps=[
        _hils_fail(1, _at(18, 10, 0)),
        _hils_fail(2, _at(18, 13, 0)),
        _hils_fail(3, _at(18, 16, 0), {
            "requires_watch": "test_failure_streak:regen_coord",
            "routed_teams": ["integrated_control"],
            "floor": "notify_now",
        }),
    ]),
    "s0_noise": Scenario(id="s0_noise", title_ja="知らせるべきでない変更", steps=[
        _change("ce-s0-1", _at(18, 17, 30), "SPEC-BRK-04", "description",
                "ブレーキペダル位置から目標原則度を求め、回生と油圧に配分する。",
                "ブレーキペダル位置から目標減速度を求め、回生と油圧に配分する。", {
                    "routed_teams": ["integrated_control"],
                    "floor": "silent",
                }),
    ]),
    "s3_morning": Scenario(id="s3_morning", title_ja="朝のブリーフィング", steps=[
        _clock(_at(19, 8, 0)),
    ]),
    "s4_release_gap": Scenario(id="s4_release_gap", title_ja="リリース前の抜け漏れチェック", steps=[
        _clock(_at(23, 8, 0), release_id="R3", unverified_requirements=7, open_reviews=3, unverified_safety=2),
    ]),
}

SCENARIO_ORDER: list[str] = [
    "s1_signal_period", "s5_watch_memory", "s2_hils_streak", "s0_noise", "s3_morning", "s4_release_gap",
]
