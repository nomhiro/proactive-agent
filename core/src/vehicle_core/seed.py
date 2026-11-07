"""架空の車種「架空SUV」（EV）の開発データ。

登場する会社・車種・人物・データはすべて架空。毎回同じ内容を返す。

シナリオが成り立つための決まりごと:
- SIG-BrkPedalPos の周期を変えると、影響を受けるのはモデル2つとテスト6つ（計8件）だけ
  （ほかのデータは SIG-BrkPedalPos、MDL-RegenCoord、MDL-MotorTq、TC-HILS-031〜035/012 にリンクしない）
- R3 のリリース前の抜け漏れは、未検証の要求 7、未完了のレビュー 3、未検証の安全要求 2
- 回生協調（regen_coord）の試験の最新結果はすべて pass（REQ-112 は検証済み）
"""

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from .constants import JST, Team
from .models import Artifact, ArtifactType, Person, TeamSettings, TestRun

SEED_NOW = datetime(2026, 11, 17, 18, 0, tzinfo=JST)

_BASE = datetime(2026, 11, 2, 9, 0, tzinfo=JST)


class Dataset(BaseModel):
    artifacts: list[Artifact]
    test_runs: list[TestRun]
    team_settings: list[TeamSettings]
    people: list[Person]


_PEOPLE: list[tuple[str, str, Team, str]] = [
    ("takahashi", "高橋", Team.CHIEF_ENGINEER, "チーフエンジニア"),
    ("tanaka", "田中", Team.INTEGRATED_CONTROL, "回生協調の主担当"),
    ("yamada", "山田", Team.INTEGRATED_CONTROL, "車両運動制御の担当"),
    ("sato", "佐藤", Team.MOTOR_CONTROL, "モータートルク制御の主担当"),
    ("ito", "伊藤", Team.MOTOR_CONTROL, "インバーター制御の担当"),
    ("kobayashi", "小林", Team.BATTERY_CONTROL, "セルバランス制御の主担当"),
    ("suzuki", "鈴木", Team.EVALUATION, "HILS 評価の主担当"),
    ("watanabe", "渡辺", Team.EVALUATION, "SILS 評価の担当"),
    ("kato", "加藤", Team.SOFTWARE_INTEGRATION, "リリース管理"),
    ("yoshida", "吉田", Team.FUNCTIONAL_SAFETY, "安全要求の管理"),
]

T = ArtifactType
IC, MC, BC = Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL, Team.BATTERY_CONTROL
EV, SI, FS = Team.EVALUATION, Team.SOFTWARE_INTEGRATION, Team.FUNCTIONAL_SAFETY
R3 = ["R3"]

# (種類, ID, チーム, タイトル, 持ち主, その他の項目)
_ROWS: list[tuple[ArtifactType, str, Team, str, str, dict[str, Any]]] = [
    # リリース
    (T.RELEASE, "R3", SI, "R3 ソフトリリース", "kato", {"attributes": {"due_date": "2026-11-30"}}),
    # 車両統合制御
    (T.REQUIREMENT, "REQ-101", IC, "加速時の前後トルク配分", "yamada", {"release_ids": R3}),
    (T.REQUIREMENT, "REQ-112", IC, "回生協調：ブレーキ踏力に応じた回生量の配分", "tanaka", {"release_ids": R3}),
    (T.REQUIREMENT, "REQ-118", IC, "坂道発進時のずり下がり防止", "yamada", {"release_ids": R3}),
    (T.REQUIREMENT, "REQ-121", IC, "低μ路での回生制限", "tanaka", {"release_ids": R3}),
    (T.REQUIREMENT, "REQ-125", IC, "クリープトルクの滑らかな立ち上がり", "yamada", {"release_ids": R3}),
    (T.SPEC, "SPEC-BRK-02", IC, "前後トルク配分の制御仕様", "yamada", {"links": ["REQ-101"]}),
    (T.SPEC, "SPEC-BRK-04", IC, "回生協調の制御仕様（ブレーキペダル入力）", "tanaka",
     {"links": ["REQ-112"], "description": "ブレーキペダル位置から目標減速度を求め、回生と油圧に配分する。"}),
    (T.SIGNAL, "SIG-BrkPedalPos", IC, "ブレーキペダル位置（CAN）", "tanaka",
     {"links": ["SPEC-BRK-04"], "attributes": {"period_ms": 10, "sender": "VCU", "receivers": ["MCU", "BCU"]}}),
    (T.MODEL, "MDL-RegenCoord", IC, "回生協調制御モデル", "tanaka",
     {"links": ["SPEC-BRK-04", "SIG-BrkPedalPos"], "release_ids": R3, "version": "1.8",
      "attributes": {"assumed_period_ms": {"SIG-BrkPedalPos": 10}}}),
    # モーター制御
    (T.REQUIREMENT, "REQ-201", MC, "トルク応答：指令から 50ms 以内に 90% 到達", "sato", {"release_ids": R3}),
    (T.REQUIREMENT, "REQ-205", MC, "回生トルクの上限管理", "sato", {"release_ids": R3}),
    (T.REQUIREMENT, "REQ-210", MC, "インバーター過熱時のトルク制限", "ito", {"release_ids": R3}),
    (T.SPEC, "SPEC-MOT-03", MC, "トルク応答の制御仕様", "sato", {"links": ["REQ-201"]}),
    (T.SPEC, "SPEC-MOT-07", MC, "回生トルク上限の制御仕様", "sato", {"links": ["REQ-205"]}),
    (T.MODEL, "MDL-MotorTq", MC, "モータートルク制御モデル", "sato",
     {"links": ["SPEC-MOT-07", "SIG-BrkPedalPos"], "release_ids": R3, "version": "2.0",
      "attributes": {"assumed_period_ms": {"SIG-BrkPedalPos": 10}}}),
    # 電池制御（SIG-BrkPedalPos とは無関係）
    (T.REQUIREMENT, "REQ-301", BC, "セル電圧のばらつきを 20mV 以内に保つ", "kobayashi", {"release_ids": R3}),
    (T.REQUIREMENT, "REQ-305", BC, "低温時の充電電流制限", "kobayashi", {"release_ids": R3}),
    (T.REQUIREMENT, "REQ-312", BC, "SOC 推定誤差 3% 以内", "kobayashi", {"release_ids": R3}),
    (T.SPEC, "SPEC-BAT-02", BC, "セルバランス制御仕様", "kobayashi", {"links": ["REQ-301"]}),
    (T.SIGNAL, "SIG-CellVoltMax", BC, "最大セル電圧（CAN）", "kobayashi",
     {"links": ["SPEC-BAT-02"], "attributes": {"period_ms": 100, "sender": "BMS", "receivers": ["VCU"]}}),
    (T.MODEL, "MDL-CellBalance", BC, "セルバランス制御モデル", "kobayashi",
     {"links": ["SPEC-BAT-02", "SIG-CellVoltMax"], "release_ids": R3, "version": "1.2"}),
    # 機能安全
    (T.SAFETY_REQUIREMENT, "SR-01", FS, "意図しない加速の防止（ASIL C）", "yoshida",
     {"links": ["REQ-101"], "release_ids": R3}),
    (T.SAFETY_REQUIREMENT, "SR-02", FS, "セル過充電の防止（ASIL C）", "yoshida",
     {"links": ["REQ-301"], "release_ids": R3}),
    (T.SAFETY_REQUIREMENT, "SR-03", FS, "インバーター過熱時の安全なトルク低減（ASIL B）", "yoshida",
     {"links": ["REQ-210"], "release_ids": R3}),
    (T.SAFETY_REQUIREMENT, "SR-04", FS, "坂道でのずり下がり防止（ASIL B）", "yoshida",
     {"links": ["REQ-118"], "release_ids": R3}),
    # 評価（テスト）
    *[(T.TESTCASE, f"TC-HILS-03{i}", EV, f"回生協調 HILS 試験 {i}", "suzuki",
       {"links": ["MDL-RegenCoord", "REQ-112"], "attributes": {"feature": "regen_coord", "bench": "HILS-2"}})
      for i in range(1, 6)],
    (T.TESTCASE, "TC-HILS-012", EV, "モータートルク応答 HILS 試験", "suzuki",
     {"links": ["MDL-MotorTq", "REQ-205"], "attributes": {"feature": "motor_torque", "bench": "HILS-1"}}),
    (T.TESTCASE, "TC-HILS-301", EV, "セルバランス HILS 試験", "suzuki",
     {"links": ["MDL-CellBalance", "REQ-301"], "attributes": {"feature": "cell_balance", "bench": "HILS-3"}}),
    (T.TESTCASE, "TC-SIL-101", EV, "前後トルク配分 SILS 試験", "watanabe",
     {"links": ["SPEC-BRK-02", "REQ-101"], "attributes": {"feature": "torque_split"}}),
    (T.TESTCASE, "TC-SIL-118", EV, "坂道発進 SILS 試験", "watanabe",
     {"links": ["REQ-118"], "attributes": {"feature": "hill_start"}}),
    (T.TESTCASE, "TC-SIL-210", EV, "インバーター過熱 SILS 試験", "watanabe",
     {"links": ["REQ-210"], "attributes": {"feature": "inverter_derate"}}),
    (T.TESTCASE, "TC-SAF-01", EV, "意図しない加速の故障注入試験", "watanabe",
     {"links": ["SR-01"], "attributes": {"feature": "safety_unintended_accel"}}),
    (T.TESTCASE, "TC-SAF-02", EV, "過充電の故障注入試験", "watanabe",
     {"links": ["SR-02"], "attributes": {"feature": "safety_overcharge"}}),
    (T.TESTCASE, "TC-SAF-03", EV, "インバーター過熱の故障注入試験", "watanabe",
     {"links": ["SR-03"], "attributes": {"feature": "safety_inverter_overheat"}}),
    # レビュー（R3 対象。3件が未完了）
    (T.REVIEW, "RV-01", IC, "回生協調仕様のデザインレビュー", "tanaka",
     {"links": ["SPEC-BRK-04"], "release_ids": R3, "status": "open"}),
    (T.REVIEW, "RV-02", MC, "回生トルク上限仕様のレビュー", "sato",
     {"links": ["SPEC-MOT-07"], "release_ids": R3, "status": "open"}),
    (T.REVIEW, "RV-03", BC, "セルバランス仕様のレビュー", "kobayashi",
     {"links": ["SPEC-BAT-02"], "release_ids": R3, "status": "open"}),
    (T.REVIEW, "RV-04", IC, "前後トルク配分仕様のレビュー", "yamada",
     {"links": ["SPEC-BRK-02"], "release_ids": R3, "status": "closed"}),
]

# 試験結果: (テスト ID, 古い順の結果)
_RUN_HISTORY: list[tuple[str, list[str]]] = [
    *[(f"TC-HILS-03{i}", ["fail", "pass", "pass"]) for i in range(1, 6)],
    ("TC-HILS-012", ["pass", "pass"]),
    ("TC-HILS-301", ["pass"]),
    ("TC-SIL-101", ["fail", "pass"]),
    ("TC-SIL-118", ["pass", "fail"]),
    ("TC-SIL-210", ["fail"]),
    ("TC-SAF-01", ["pass"]),
    ("TC-SAF-02", ["pass"]),
    ("TC-SAF-03", ["fail"]),
]


def _artifacts() -> list[Artifact]:
    return [
        Artifact(id=id_, type=type_, team=team, title=title, owner=owner,
                 updated_at=_BASE + timedelta(hours=6 * n), **extra)
        for n, (type_, id_, team, title, owner, extra) in enumerate(_ROWS)
    ]


def _test_runs(artifacts: list[Artifact]) -> list[TestRun]:
    feature = {a.id: a.attributes["feature"] for a in artifacts if a.type == ArtifactType.TESTCASE}
    runs: list[TestRun] = []
    for tc_id, results in _RUN_HISTORY:
        for k, result in enumerate(results):
            # 1日おきに並べ、最新の結果が SEED_NOW の4時間前になるようにする
            executed_at = SEED_NOW - timedelta(days=len(results) - 1 - k, hours=4)
            runs.append(TestRun(id=f"run-{tc_id}-{k + 1}", testcase_id=tc_id, feature=feature[tc_id],
                                result=result, executed_at=executed_at))
    return runs


def build_dataset() -> Dataset:
    artifacts = _artifacts()
    people = [Person(id=i, name_ja=n, team=t, role=r) for i, n, t, r in _PEOPLE]
    settings = [
        TeamSettings(id=f"ts-{team.value}", team=team, members=[p for p in people if p.team == team])
        for team in Team
    ]
    return Dataset(artifacts=artifacts, test_runs=_test_runs(artifacts), team_settings=settings, people=people)
