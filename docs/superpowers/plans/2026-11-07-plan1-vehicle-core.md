# Plan 1: vehicle_core（判定ロジックと架空データ）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 設計書のうち「決まった手順で求まるもの」（データの型、架空データ、影響範囲、リリースの抜け漏れ、見張りの判定、知らせ方の判定、振り分け、書き込み窓口の検査、エスカレーションの判定、デモのシナリオ）を、Azure なしで動いてテストできる Python パッケージ `vehicle_core` として作る。

**Architecture:** uv ワークスペースのルートに `core/` パッケージを置く。後続の Functions（Plan 2）、エージェント（Plan 3）、Web の BFF（Plan 4）はすべてこのパッケージを import する。LLM も Azure SDK も使わない純粋なロジックだけを置く。

**Tech Stack:** Python 3.12+、pydantic v2、tzdata（Windows で `Asia/Tokyo` を引くため）、pytest、uv

**Spec:** `docs/superpowers/specs/2026-11-07-proactive-vehicle-agent-design.md`（特に 3 章、4.2 節、5.3 節、7.2〜7.5 節、9 章）

### 計画全体の中での位置づけ
| 計画 | 中身 | 前提 |
|---|---|---|
| **Plan 1（本書）** | `vehicle_core`: 判定ロジックと架空データ | なし |
| Plan 2 | azd + Bicep の基盤（Cosmos DB、Functions、Storage、Web PubSub、App Insights）、Functions（振り分け、まとめ、定時実行、メール配達、書き込み窓口）、シード投入 | Plan 1 |
| Plan 3 | Foundry ホステッドエージェント4体（ツール、Memory、A2A）、Container Apps Sandboxes による解析 | Plan 1, 2 |
| Plan 4 | Web アプリ（会話・マップ・見張りの3区画、人物の切り替え、承認、Web PubSub）、シナリオを進める仕組み、シナリオテスト | Plan 1〜3 |

## Global Constraints

- `requires-python = ">=3.12"`。依存は `pydantic>=2.9`、`tzdata` のみ（開発用に `pytest>=8`）
- 車種 ID は `VEHICLE_ID = "kakuu-suv"`。すべての文書に `vehicle_id` を持たせる（Cosmos のパーティションキー `/vehicleId` に対応。JSON 上のキー名は `vehicle_id` のまま使い、Plan 2 で `/vehicle_id` をパーティションキーにする）
- 日時はすべてタイムゾーン付き。基準は `Asia/Tokyo`（JST）。タイムゾーンなしの日時を受け取ったら `ValueError`
- 登場する会社・車種・人物・データはすべて架空。実在の会社名・製品名を使わない
- エージェントがいるチームは4つだけ: `chief_engineer`、`integrated_control`、`motor_control`、`evaluation`（設計書 4.3 節）
- 連続変更のまとめの窓: 180 秒（設計書 7.3 節の目安「2〜5分」から【計画での決定】）
- 静かな時間帯: 20:00 以上〜08:00 未満（設計書 7.4 節「20:00〜翌 7:59」）
- 人への返事の期限: 48 時間（設計書 4.2 節「期限内に返事がない」の期限。【計画での決定】）
- 画面に出る文字列（チーム名など）は日本語

### 設計書の隙間を埋めた決定（実装者はこのとおりに作る）
1. **振り分け先**: 変更イベントの調査依頼は「変更されたデータを持つチーム」と「その変更に合う見張りを持つチーム」だけに出す。影響を受けるだけのチームには出さない。影響を受けるチームへの連絡は、発信元チームの承認を経た `impact_notice` で届ける（設計書 4.2 節の承認の原則と、シナリオ1の流れを両立させるため）
2. **知らせ方の下限**: 設計書 7.4 節の「すぐ知らせる」条件（安全要求、リリースに響く、即時の見張り）はコードで判定し、下限とする。LLM はそれより上げることはできるが、下げることはできない。タイトルと説明だけの変更（編集上の変更）は下限を `silent` にする
3. **統括エージェントが前に出る条件**: リリースに響く件は、統括の朝のブリーフィングに「リスク」として入れる（判定は Plan 3）。チーフエンジニアに判断を仰ぐ案件（`escalation`）になるのは、人が「できない」と返したとき、または 48 時間返事がないときだけ
4. **人の返事の扱い**: `human_reply` は、自チームの人が書いた `messages` の ID（`source_message_id`）を必ず持つ。書き込み窓口は、その ID が自チームの人間の発言であることを確かめる。エージェントが人の返事をでっち上げることを防ぐ
5. **見張りが二度鳴らない**: 失敗の連続回数の見張りは、連続回数が設定値に「ちょうど」達したときだけ鳴る（4回目、5回目では鳴らない）

## Review Focus

1. **リンクの循環や存在しない ID へのリンク**（データの入力ミスで起こりうる）→ 影響範囲の探索が止まり、存在しない ID は無視する。テストは Task 3 に入れる
2. **Cosmos から UTC やタイムゾーンなしの日時が来る** → JST に直して判定する。タイムゾーンなしは `ValueError`。テストは Task 1 と Task 6 に入れる
3. **静かな時間帯のちょうど境目（20:00:00 と 08:00:00）** → 20:00:00 は静か、08:00:00 は静かでない。テストは Task 6 に入れる
4. **存在しないデータへの変更イベント、エージェントのいないチームのデータへの変更** → 調査依頼は出ない（例外も出ない）。テストは Task 7 に入れる
5. **書き込み窓口に、チームの判別できない呼び出しが来る**（トークンのクレームなし、未知のチーム名）→ 拒否する。テストは Task 8 に入れる

---

## ファイル構成

```
pyproject.toml                     # uv ワークスペースのルート（members = ["core"]）
core/
  pyproject.toml                   # name = "vehicle-core"
  src/vehicle_core/
    __init__.py
    constants.py                   # VEHICLE_ID, JST, Team, AGENT_TEAMS, TEAM_LABELS_JA, 各種窓と期限
    clock.py                       # Clock, SystemClock, VirtualClock, to_jst
    models.py                      # すべての文書の型（pydantic）
    seed.py                        # 架空データの生成
    impact.py                      # Graph, ImpactResult, analyze_impact
    release_gaps.py                # ReleaseGapReport, release_gaps
    watches.py                     # 見張りの判定、失敗の連続回数
    notify_policy.py               # 知らせ方の下限、配達のタイミング
    routing.py                     # InvestigationRequest, route_change, route_test_run, coalesce
    gateway.py                     # 書き込み窓口の検査
    escalation.py                  # エスカレーションの判定
    scenarios.py                   # デモのシナリオ定義
  tests/
    conftest.py                    # dataset / graph の fixture
    test_models.py  test_clock.py  test_seed.py  test_impact.py  test_release_gaps.py
    test_watches.py test_notify_policy.py test_routing.py test_gateway.py
    test_escalation.py test_scenarios.py
```

テストの実行は常に `uv run --directory core pytest <path> -v`。

---

### Task 1: ワークスペース、定数、時計、データの型

**Files:**
- Create: `pyproject.toml`, `core/pyproject.toml`, `core/src/vehicle_core/__init__.py`, `core/src/vehicle_core/constants.py`, `core/src/vehicle_core/clock.py`, `core/src/vehicle_core/models.py`
- Test: `core/tests/test_clock.py`, `core/tests/test_models.py`

**Interfaces:**
- Produces（`constants.py`）:
  - `VEHICLE_ID: str = "kakuu-suv"`、`JST = ZoneInfo("Asia/Tokyo")`
  - `class Team(StrEnum)`: `CHIEF_ENGINEER="chief_engineer"`, `INTEGRATED_CONTROL="integrated_control"`, `MOTOR_CONTROL="motor_control"`, `BATTERY_CONTROL="battery_control"`, `EVALUATION="evaluation"`, `SOFTWARE_INTEGRATION="software_integration"`, `FUNCTIONAL_SAFETY="functional_safety"`
  - `AGENT_TEAMS: frozenset[Team]`（上記4チーム）
  - `TEAM_LABELS_JA: dict[Team, str]`: 車種統括 / 車両統合制御 / モーター制御 / 電池制御 / 評価 / ソフト統合 / 機能安全
  - `DEBOUNCE_WINDOW = timedelta(seconds=180)`、`REPLY_DEADLINE = timedelta(hours=48)`、`QUIET_START = time(20, 0)`、`QUIET_END = time(8, 0)`、`DIGEST_TIME = time(8, 0)`
- Produces（`clock.py`）:
  - `to_jst(dt: datetime) -> datetime`（タイムゾーンなしは `ValueError`）
  - `class Clock(Protocol): def now(self) -> datetime`
  - `class SystemClock`、`class VirtualClock(start: datetime)` に `now()`, `advance(delta: timedelta) -> None`, `set(dt: datetime) -> None`（`now()` は常に JST で返す）
- Produces（`models.py`、すべて `pydantic.BaseModel`、日時は `AwareDatetime`、`vehicle_id: str = VEHICLE_ID`）:
  - `class ArtifactType(StrEnum)`: `requirement`, `spec`, `signal`, `model`, `testcase`, `safety_requirement`, `release`, `review`
  - `Artifact`: `id, vehicle_id, type: ArtifactType, team: Team, title: str, description: str = "", owner: str, version: str = "1.0", status: str = "active", links: list[str] = [], attributes: dict[str, Any] = {}, release_ids: list[str] = [], updated_at`
  - `FieldChange`: `path: str, before: Any, after: Any`
  - `ChangeEvent`: `id, vehicle_id, artifact_id: str, changed_by: str, changed_at, changes: list[FieldChange]`、プロパティ `is_substantive -> bool`（`EDITORIAL_FIELDS = {"title", "description"}` 以外の `path` が1つでもあれば True）
  - `TestRun`: `id, vehicle_id, testcase_id: str, feature: str, result: Literal["pass", "fail"], executed_at, log_blob: str | None = None`
  - `class WatchKind(StrEnum)`: `artifact_changed`, `test_failure_streak`
  - `class DeliveryMode(StrEnum)`: `immediate`, `digest`
  - `Watch`: `id, vehicle_id, team: Team, kind: WatchKind, description: str, target_ids: list[str] = [], feature: str | None = None, streak: int = 3, delivery: DeliveryMode, created_by: str, created_at`
  - `class Classification(StrEnum)`: `silent`, `digest`, `notify_now`（この順に強い）
  - `class Proactivity(StrEnum)`: `off`, `important_only`, `normal`, `frequent`
  - `Person`: `id: str, name_ja: str, team: Team, role: str`
  - `TeamSettings`: `id, vehicle_id, team: Team, proactivity: Proactivity = normal, quiet_start: time = QUIET_START, quiet_end: time = QUIET_END, members: list[Person] = []`
  - `class MailKind(StrEnum)`: `analysis_request`, `analysis_result`, `question`, `answer`, `impact_notice`, `human_reply`, `escalation`
  - `class Stance(StrEnum)`: `can`, `cannot`, `partial`, `unknown`
  - `AgentMail`: `id, vehicle_id, thread_id: str, from_team: Team, to_team: Team, kind: MailKind, body: str, related_artifact_ids: list[str] = [], source_message_id: str | None = None, stance: Stance | None = None, created_at`
  - `class MessageRole(StrEnum)`: `assistant`, `human`, `system`
  - `Message`: `id, vehicle_id, team: Team, role: MessageRole, author: str, text: str, notification_id: str | None = None, proposal_id: str | None = None, attachments: list[str] = [], created_at`
  - `class ProposalStatus(StrEnum)`: `pending`, `approved`, `rejected`
  - `Proposal`: `id, vehicle_id, team: Team, kind: MailKind, to_teams: list[Team], draft: str, related_artifact_ids: list[str] = [], thread_id: str, status: ProposalStatus = pending, decided_by: str | None = None, decided_at: AwareDatetime | None = None, created_at`
  - `Notification`: `id, vehicle_id, team: Team, origin_artifact_id: str | None, impacted_ids: list[str], highlight_ids: list[str], cross_team_edges: list[tuple[str, str]], classification: Classification, deliver_at: AwareDatetime | None, reason: str, created_at`
  - `AgentRun`: `id, vehicle_id, team: Team, state: Literal["running", "scheduled", "done"], title: str, started_at, finished_at: AwareDatetime | None = None, detail: dict[str, Any] = {}`
  - `Schedule`: `id, vehicle_id, team: Team, due_at, task: str, payload: dict[str, Any] = {}`
  - `CONTAINER_MODELS: dict[str, type[BaseModel]]`: `artifacts→Artifact, change_events→ChangeEvent, test_runs→TestRun, watches→Watch, messages→Message, proposals→Proposal, agent_mail→AgentMail, notifications→Notification, agent_runs→AgentRun, schedules→Schedule, team_settings→TeamSettings`

- [ ] **Step 1: ワークスペースを作る**

ルートの `pyproject.toml` に `[tool.uv.workspace] members = ["core"]`。`core/pyproject.toml` は `name = "vehicle-core"`、`requires-python = ">=3.12"`、`dependencies = ["pydantic>=2.9", "tzdata"]`、`[dependency-groups] dev = ["pytest>=8"]`、ビルドは hatchling で `src/vehicle_core`。

- [ ] **Step 2: 失敗するテストを書く**

```python
# core/tests/test_clock.py
def test_to_jst_converts_utc():
    utc = datetime(2026, 11, 17, 12, 10, tzinfo=timezone.utc)
    assert to_jst(utc) == datetime(2026, 11, 17, 21, 10, tzinfo=JST)

def test_to_jst_rejects_naive():
    with pytest.raises(ValueError):
        to_jst(datetime(2026, 11, 17, 21, 10))

def test_virtual_clock_advance_and_set():
    c = VirtualClock(datetime(2026, 11, 17, 21, 10, tzinfo=JST))
    c.advance(timedelta(hours=11))
    assert c.now() == datetime(2026, 11, 18, 8, 10, tzinfo=JST)
    c.set(datetime(2026, 11, 23, 8, 0, tzinfo=JST))
    assert c.now().day == 23

def test_virtual_clock_rejects_naive_start():
    with pytest.raises(ValueError):
        VirtualClock(datetime(2026, 11, 17))
```

```python
# core/tests/test_models.py
def test_change_event_editorial_only_is_not_substantive():
    ev = ChangeEvent(id="e1", artifact_id="SPEC-BRK-04", changed_by="tanaka",
                     changed_at=datetime(2026, 11, 18, 14, 0, tzinfo=JST),
                     changes=[FieldChange(path="description", before="a", after="b")])
    assert ev.is_substantive is False

def test_change_event_attribute_change_is_substantive():
    ev = ChangeEvent(id="e2", artifact_id="SIG-BrkPedalPos", changed_by="tanaka",
                     changed_at=datetime(2026, 11, 17, 21, 10, tzinfo=JST),
                     changes=[FieldChange(path="attributes.period_ms", before=10, after=20)])
    assert ev.is_substantive is True

def test_models_reject_naive_datetime():
    with pytest.raises(ValidationError):
        Artifact(id="X", type="requirement", team="integrated_control", title="t",
                 owner="tanaka", updated_at=datetime(2026, 11, 1))

def test_artifact_json_roundtrip_keeps_vehicle_id():
    a = Artifact(id="REQ-112", type="requirement", team="integrated_control", title="回生協調",
                 owner="tanaka", updated_at=datetime(2026, 11, 1, tzinfo=JST))
    d = a.model_dump(mode="json")
    assert d["vehicle_id"] == "kakuu-suv"
    assert Artifact.model_validate(d) == a

def test_agent_teams_are_exactly_four():
    assert AGENT_TEAMS == {Team.CHIEF_ENGINEER, Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL, Team.EVALUATION}
```

- [ ] **Step 3: 失敗を確かめる**

Run: `uv run --directory core pytest tests/test_clock.py tests/test_models.py -v`
Expected: FAIL（`ModuleNotFoundError: vehicle_core...`）

- [ ] **Step 4: `constants.py`、`clock.py`、`models.py` を Interfaces のとおり実装する**

- [ ] **Step 5: 通ることを確かめる**

Run: `uv run --directory core pytest tests/test_clock.py tests/test_models.py -v`
Expected: PASS（9 件）

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml core/ uv.lock
git commit -m "feat(core): ワークスペース、定数、時計、データの型を追加"
```

---

### Task 2: 架空データの生成

**Files:**
- Create: `core/src/vehicle_core/seed.py`, `core/tests/conftest.py`
- Test: `core/tests/test_seed.py`

**Interfaces:**
- Consumes: Task 1 の型
- Produces:
  - `class Dataset(BaseModel)`: `artifacts: list[Artifact], test_runs: list[TestRun], team_settings: list[TeamSettings], people: list[Person]`
  - `def build_dataset() -> Dataset`（毎回同じ内容を返す。乱数を使うなら固定シード）
  - `SEED_NOW = datetime(2026, 11, 17, 18, 0, tzinfo=JST)`（シードの `updated_at` / `executed_at` はこれ以前）
  - `conftest.py` の fixture: `dataset() -> Dataset`、`graph() -> Graph`（`graph` は Task 3 で追加）

データの決まりごと（シナリオが成り立つための値。これ以外の件数・名前は実装者裁量）:
- 人物（`Person.id`）: `tanaka`（integrated_control、回生協調の主担当）、`sato`（motor_control）、`suzuki`（evaluation）、`takahashi`（chief_engineer、チーフエンジニア）。ほかに各チーム1〜2名
- リリース: `R3`（type `release`、team `software_integration`、`attributes.due_date = "2026-11-30"`）
- 信号 `SIG-BrkPedalPos`: team `integrated_control`、`links=["SPEC-BRK-04"]`、`attributes={"period_ms": 10, "sender": "VCU", "receivers": ["MCU", "BCU"]}`
- 仕様 `SPEC-BRK-04`: integrated_control、`links=["REQ-112"]`
- 要求 `REQ-112`（回生協調）: integrated_control、`release_ids=["R3"]`
- モデル `MDL-RegenCoord`: integrated_control、`version="1.8"`、`links=["SPEC-BRK-04", "SIG-BrkPedalPos"]`、`release_ids=["R3"]`、`attributes={"assumed_period_ms": {"SIG-BrkPedalPos": 10}}`
- 要求 `REQ-201`（トルク応答）、`REQ-205`（回生上限）、仕様 `SPEC-MOT-07`（links `["REQ-205"]`）: motor_control
- モデル `MDL-MotorTq`: motor_control、`version="2.0"`、`links=["SPEC-MOT-07", "SIG-BrkPedalPos"]`、`release_ids=["R3"]`、`attributes={"assumed_period_ms": {"SIG-BrkPedalPos": 10}}`
- テスト `TC-HILS-031`〜`TC-HILS-035`: team evaluation、`links=["MDL-RegenCoord", "REQ-112"]`、`attributes.feature = "regen_coord"`
- テスト `TC-HILS-012`: evaluation、`links=["MDL-MotorTq", "REQ-205"]`、`attributes.feature = "motor_torque"`
- 安全要求 `SR-*`: functional_safety。`TC-HILS-031`〜`035` と `TC-HILS-012` は安全要求にリンクしない
- 電池制御の要求・仕様・モデル・テストを数件（`SIG-BrkPedalPos` とは無関係）
- R3 のリリース前の抜け漏れが、ちょうど次の件数になるようにする（Task 4 で使う。定義は Task 4 の Interfaces を参照）: 未検証の要求 7、未完了のレビュー 3、未検証の安全要求 2
- `team_settings`: 7チームすべて。proactivity は全チーム `normal`

- [ ] **Step 1: 失敗するテストを書く**

```python
# core/tests/test_seed.py
def test_build_dataset_is_deterministic():
    assert build_dataset() == build_dataset()

def test_all_links_resolve(dataset):
    ids = {a.id for a in dataset.artifacts}
    for a in dataset.artifacts:
        assert set(a.links) <= ids, a.id
        assert set(a.release_ids) <= ids, a.id

def test_ids_are_unique(dataset):
    ids = [a.id for a in dataset.artifacts]
    assert len(ids) == len(set(ids))

def test_scenario_critical_values(dataset):
    by_id = {a.id: a for a in dataset.artifacts}
    assert by_id["SIG-BrkPedalPos"].attributes["period_ms"] == 10
    assert by_id["MDL-RegenCoord"].version == "1.8"
    assert by_id["MDL-MotorTq"].team == Team.MOTOR_CONTROL
    assert by_id["R3"].attributes["due_date"] == "2026-11-30"

def test_core_people_exist(dataset):
    assert {"tanaka", "sato", "suzuki", "takahashi"} <= {p.id for p in dataset.people}

def test_seed_timestamps_before_seed_now(dataset):
    assert all(a.updated_at <= SEED_NOW for a in dataset.artifacts)
    assert all(r.executed_at <= SEED_NOW for r in dataset.test_runs)

def test_no_real_company_names(dataset):
    banned = ["トヨタ", "ホンダ", "日産", "Toyota", "Honda", "Nissan", "Denso", "デンソー"]
    text = dataset.model_dump_json()
    assert not any(b in text for b in banned)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --directory core pytest tests/test_seed.py -v`
Expected: FAIL（`build_dataset` がない）

- [ ] **Step 3: `build_dataset() -> Dataset` を `seed.py` に実装し、`conftest.py` に `dataset` fixture を置く**

上の決まりごとの値はそのまま書く。それ以外の件数は少なめでよい（全体で 40〜60 件程度）。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --directory core pytest tests/test_seed.py -v`
Expected: PASS（7 件）

- [ ] **Step 5: Commit**

```bash
git add core/src/vehicle_core/seed.py core/tests/conftest.py core/tests/test_seed.py
git commit -m "feat(core): 架空の車種開発データを生成"
```

---

### Task 3: 影響範囲の探索

**Files:**
- Create: `core/src/vehicle_core/impact.py`
- Modify: `core/tests/conftest.py`（`graph` fixture を追加）
- Test: `core/tests/test_impact.py`

**Interfaces:**
- Consumes: `Artifact`, `ArtifactType`, `Team`, `Dataset`
- Produces:
  - `class UnknownArtifact(KeyError)`
  - `class Graph`: `Graph.from_artifacts(artifacts: Iterable[Artifact]) -> Graph`、`get(id) -> Artifact`（ない ID は `UnknownArtifact`）、`has(id) -> bool`、`downstream(id) -> set[str]`（その ID を `links` に持つものを再帰的に辿る。起点は含まない）、`upstream(id) -> set[str]`（`links` を再帰的に辿る。起点は含まない）
  - `class ImpactResult(BaseModel)`: `origin_id: str, origin_team: Team, impacted_ids: list[str]`（昇順）、`impacted_by_team: dict[Team, list[str]]`（各リスト昇順）、`cross_team_edges: list[tuple[str, str]]`（親子でチームが違うリンク。`(親, 子)`。探索で通ったものだけ。昇順）、`highlight_ids: list[str]`（上流 ∪ 起点 ∪ 影響。昇順）、`affects_release_ids: list[str]`（起点と影響を受けるものの `release_ids` の和集合。昇順）、`touches_safety: bool`（影響を受けるものに安全要求があるか、影響を受けるテストが安全要求に `links` しているか）
  - `def analyze_impact(graph: Graph, origin_id: str) -> ImpactResult`

チームの比較: `impacted_by_team` と `cross_team_edges` で使うチームは、テスト（type `testcase`）については「リンク先のモデルのチーム」とする（テストの持ち主は評価チームだが、影響を受ける領域はモデルの領域だから）。リンク先にモデルがないテストは自分の `team` を使う。

- [ ] **Step 1: 失敗するテストを書く**

```python
# core/tests/test_impact.py
def test_signal_period_change_impact(graph):
    r = analyze_impact(graph, "SIG-BrkPedalPos")
    assert r.origin_team == Team.INTEGRATED_CONTROL
    assert r.impacted_ids == sorted(["MDL-RegenCoord", "MDL-MotorTq", "TC-HILS-012",
        "TC-HILS-031", "TC-HILS-032", "TC-HILS-033", "TC-HILS-034", "TC-HILS-035"])
    assert r.impacted_by_team[Team.INTEGRATED_CONTROL] == sorted(["MDL-RegenCoord",
        "TC-HILS-031", "TC-HILS-032", "TC-HILS-033", "TC-HILS-034", "TC-HILS-035"])
    assert r.impacted_by_team[Team.MOTOR_CONTROL] == ["MDL-MotorTq", "TC-HILS-012"]
    assert r.cross_team_edges == [("SIG-BrkPedalPos", "MDL-MotorTq")]
    assert {"REQ-112", "SPEC-BRK-04", "SIG-BrkPedalPos"} <= set(r.highlight_ids)
    assert r.affects_release_ids == ["R3"]
    assert r.touches_safety is False

def test_battery_artifacts_not_in_signal_impact(graph, dataset):
    battery_ids = {a.id for a in dataset.artifacts if a.team == Team.BATTERY_CONTROL}
    r = analyze_impact(graph, "SIG-BrkPedalPos")
    assert not battery_ids & set(r.highlight_ids)

def test_unknown_origin_raises(graph):
    with pytest.raises(UnknownArtifact):
        analyze_impact(graph, "NOPE-1")

def test_cycle_terminates():
    t = datetime(2026, 11, 1, tzinfo=JST)
    a = Artifact(id="A", type="spec", team="integrated_control", title="a", owner="x", links=["B"], updated_at=t)
    b = Artifact(id="B", type="spec", team="integrated_control", title="b", owner="x", links=["A"], updated_at=t)
    r = analyze_impact(Graph.from_artifacts([a, b]), "A")
    assert r.impacted_ids == ["B"]

def test_dangling_link_ignored():
    t = datetime(2026, 11, 1, tzinfo=JST)
    a = Artifact(id="A", type="model", team="motor_control", title="a", owner="x", links=["GONE"], updated_at=t)
    g = Graph.from_artifacts([a])
    assert g.upstream("A") == set()

def test_safety_detected_when_impacted_test_links_safety_requirement():
    t = datetime(2026, 11, 1, tzinfo=JST)
    sr = Artifact(id="SR-1", type="safety_requirement", team="functional_safety", title="s", owner="x", updated_at=t)
    m = Artifact(id="M", type="model", team="motor_control", title="m", owner="x", updated_at=t)
    tc = Artifact(id="TC", type="testcase", team="evaluation", title="t", owner="x", links=["M", "SR-1"], updated_at=t)
    assert analyze_impact(Graph.from_artifacts([sr, m, tc]), "M").touches_safety is True
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --directory core pytest tests/test_impact.py -v`
Expected: FAIL（`vehicle_core.impact` がない）

- [ ] **Step 3: `impact.py` を Interfaces のとおり実装し、`conftest.py` に `graph` fixture（`Graph.from_artifacts(dataset.artifacts)`）を足す**

探索は訪問済み集合を持つ幅優先探索。逆引き（子の一覧）は `from_artifacts` で一度作る。存在しない ID へのリンクは無視する。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --directory core pytest tests/test_impact.py -v`
Expected: PASS（6 件）

- [ ] **Step 5: Commit**

```bash
git add core/src/vehicle_core/impact.py core/tests/conftest.py core/tests/test_impact.py
git commit -m "feat(core): トレーサビリティを辿る影響範囲の探索を追加"
```

---

### Task 4: リリース前の抜け漏れの集計

**Files:**
- Create: `core/src/vehicle_core/release_gaps.py`
- Test: `core/tests/test_release_gaps.py`

**Interfaces:**
- Consumes: `Dataset`, `Artifact`, `TestRun`
- Produces:
  - `class ReleaseGapReport(BaseModel)`: `release_id: str, unverified_requirement_ids: list[str], open_review_ids: list[str], unverified_safety_ids: list[str]`（すべて昇順）
  - `def latest_result(runs: Iterable[TestRun], testcase_id: str) -> Literal["pass", "fail"] | None`（`executed_at` が最も新しいもの）
  - `def release_gaps(dataset: Dataset, release_id: str) -> ReleaseGapReport`

定義（設計書 5.3 節シナリオ4）:
- 対象の要求: type `requirement` で `release_ids` に `release_id` を含むもの
- 検証済みの要求: その要求の ID を `links` に持つテストのうち、最新の結果が `pass` のものが1つ以上ある
- 未完了のレビュー: type `review`、`release_ids` に含む、`status != "closed"`
- 対象の安全要求: type `safety_requirement` で `release_ids` に含むもの。検証済みの定義は要求と同じ

- [ ] **Step 1: 失敗するテストを書く**

```python
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
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --directory core pytest tests/test_release_gaps.py -v`
Expected: FAIL

- [ ] **Step 3: `release_gaps.py` を実装する。件数が 7 / 3 / 2 にならなければ `seed.py` のデータを調整する（シード側の決まりごとは Task 2 のとおり）**

注意: `REQ-112` はシード時点では検証済み（`TC-HILS-031` などの最新が `pass`）にしておく。3つ目のテストが成り立つための前提になる。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --directory core pytest tests/test_release_gaps.py tests/test_seed.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/vehicle_core/release_gaps.py core/src/vehicle_core/seed.py core/tests/test_release_gaps.py
git commit -m "feat(core): リリース前の抜け漏れの集計を追加"
```

---

### Task 5: 見張りの判定

**Files:**
- Create: `core/src/vehicle_core/watches.py`
- Test: `core/tests/test_watches.py`

**Interfaces:**
- Consumes: `Watch`, `WatchKind`, `TestRun`, `ImpactResult`
- Produces:
  - `def match_change_watches(watches: Iterable[Watch], impact: ImpactResult) -> list[Watch]`: `artifact_changed` のうち、`target_ids` が「起点 ∪ 影響を受けるもの」と交わるもの
  - `def failure_streak(runs: Iterable[TestRun], feature: str) -> int`: その `feature` の結果を `executed_at` の新しい順に見て、`fail` が続く数
  - `def match_test_watches(watches: Iterable[Watch], runs: Iterable[TestRun], new_run: TestRun) -> list[Watch]`: `test_failure_streak` のうち `feature == new_run.feature` で、`new_run` を含めた連続回数が `watch.streak` と**ちょうど等しい**もの（`runs` に `new_run` が含まれていてもいなくても同じ結果になること）

- [ ] **Step 1: 失敗するテストを書く**

```python
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
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --directory core pytest tests/test_watches.py -v`
Expected: FAIL

- [ ] **Step 3: `watches.py` を実装する**

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --directory core pytest tests/test_watches.py -v`
Expected: PASS（5 件）

- [ ] **Step 5: Commit**

```bash
git add core/src/vehicle_core/watches.py core/tests/test_watches.py
git commit -m "feat(core): 見張り条件の判定を追加"
```

---

### Task 6: 知らせ方の判定（下限と配達のタイミング）

**Files:**
- Create: `core/src/vehicle_core/notify_policy.py`
- Test: `core/tests/test_notify_policy.py`

**Interfaces:**
- Consumes: `Classification`, `Proactivity`, `TeamSettings`, `Watch`, `DeliveryMode`, `ImpactResult`, `to_jst`, 定数
- Produces:
  - `def floor_classification(impact: ImpactResult | None, substantive: bool, matched: Iterable[Watch]) -> Classification`
    - `substantive` かつ `impact.touches_safety` → `notify_now`
    - `substantive` かつ `impact.affects_release_ids` が空でない → `notify_now`
    - `matched` に `delivery == immediate` がある → `notify_now`
    - `matched` に `delivery == digest` がある → `digest`
    - それ以外 → `silent`
  - `def final_classification(floor: Classification, llm: Classification) -> Classification`: 強い方（`silent < digest < notify_now`）
  - `def is_quiet(now: datetime, settings: TeamSettings) -> bool`: JST の時刻が `quiet_start` 以上、または `quiet_end` 未満
  - `def next_time_at(now: datetime, t: time) -> datetime`: `now` 以降で最初の JST の時刻 `t`（`now` がちょうど `t` なら `now`）
  - `class DeliveryDecision(BaseModel)`: `mode: Literal["immediate", "digest", "none"], deliver_at: AwareDatetime | None`
  - `def decide_delivery(classification: Classification, touches_safety: bool, now: datetime, settings: TeamSettings) -> DeliveryDecision`
    - `touches_safety` → `immediate`、`deliver_at = now`（時間帯と頻度設定に関係なく）
    - `proactivity == off` → `none`
    - `silent` → `none`
    - `digest`: `important_only` → `none`。`frequent` → `notify_now` と同じ扱い。それ以外 → `digest`、`deliver_at = next_time_at(now, DIGEST_TIME)`
    - `notify_now`: 静かな時間帯なら `immediate`、`deliver_at = next_time_at(now, settings.quiet_end)`。そうでなければ `immediate`、`deliver_at = now`
  - `now` は `to_jst` を通す（タイムゾーンなしは `ValueError`）

- [ ] **Step 1: 失敗するテストを書く**

```python
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
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --directory core pytest tests/test_notify_policy.py -v`
Expected: FAIL

- [ ] **Step 3: `notify_policy.py` を実装する**

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --directory core pytest tests/test_notify_policy.py -v`
Expected: PASS（8 件）

- [ ] **Step 5: Commit**

```bash
git add core/src/vehicle_core/notify_policy.py core/tests/test_notify_policy.py
git commit -m "feat(core): 知らせ方の下限と配達タイミングの判定を追加"
```

---

### Task 7: 振り分け（調査依頼の作成、冪等キー、まとめ）

**Files:**
- Create: `core/src/vehicle_core/routing.py`
- Test: `core/tests/test_routing.py`

**Interfaces:**
- Consumes: `Graph`, `analyze_impact`, `UnknownArtifact`, `match_change_watches`, `match_test_watches`, `floor_classification`, `ChangeEvent`, `TestRun`, `Watch`, `AGENT_TEAMS`, `DEBOUNCE_WINDOW`
- Produces:
  - `class InvestigationRequest(BaseModel)`: `id: str`（冪等キー）、`vehicle_id: str = VEHICLE_ID`、`team: Team`、`trigger: Literal["change", "test_run", "schedule", "mail"]`、`origin_artifact_id: str | None`、`source_ids: list[str]`（変更イベント ID や試験結果 ID。昇順）、`impact: ImpactResult | None`、`matched_watch_ids: list[str]`、`floor: Classification`、`not_before: AwareDatetime`
  - `def idempotency_key(team: Team, trigger: str, source_ids: Iterable[str]) -> str`: `f"{team}|{trigger}|{','.join(sorted(set(source_ids)))}"` の SHA-256 の16進先頭32文字
  - `def route_change(event: ChangeEvent, graph: Graph, watches: Iterable[Watch]) -> list[InvestigationRequest]`
    - 起点が存在しない → `[]`
    - 宛先 = 起点のチーム ∪ 合致した見張りのチーム、のうち `AGENT_TEAMS` に入るもの（テストの場合も起点の `team` をそのまま使う）
    - `floor` は `floor_classification(impact, event.is_substantive, そのチームの合致した見張り)`
    - `not_before = event.changed_at + DEBOUNCE_WINDOW`
    - チームの昇順で返す
  - `def route_test_run(new_run: TestRun, runs: Iterable[TestRun], graph: Graph, watches: Iterable[Watch]) -> list[InvestigationRequest]`
    - 宛先 = テストのリンク先モデルのチーム（なければテストの `team`）と、合致した見張りのチーム。`AGENT_TEAMS` に入るものだけ。結果が `pass` で見張りにも合致しなければ `[]`
    - `impact = None`、`origin_artifact_id = new_run.testcase_id`、`floor` は見張りから（`floor_classification(None, False, matched)`）、`not_before = new_run.executed_at`（まとめない）
  - `def coalesce(pending: Iterable[InvestigationRequest]) -> list[InvestigationRequest]`: `trigger == "change"` のものを `(team, origin_artifact_id)` で束ね、`not_before` の間隔が `DEBOUNCE_WINDOW` 以内に連なるものを1件にする。`source_ids` は和集合、`id` は再計算、`not_before` は最も遅いもの、`floor` は最も強いもの、`impact` は最も遅いもののもの。ほかの trigger はそのまま返す

- [ ] **Step 1: 失敗するテストを書く**

```python
def ev(id_, artifact, minute, path="attributes.period_ms"):
    return ChangeEvent(id=id_, artifact_id=artifact, changed_by="tanaka",
                       changed_at=datetime(2026, 11, 17, 21, minute, tzinfo=JST),
                       changes=[FieldChange(path=path, before=10, after=20)])

def test_signal_change_routes_only_to_owner_team(graph):
    reqs = route_change(ev("e1", "SIG-BrkPedalPos", 10), graph, [])
    assert [r.team for r in reqs] == [Team.INTEGRATED_CONTROL]
    r = reqs[0]
    assert r.floor == Classification.NOTIFY_NOW
    assert len(r.impact.impacted_ids) == 8
    assert r.not_before == datetime(2026, 11, 17, 21, 13, tzinfo=JST)

def test_watching_team_also_receives(graph):
    w = Watch(id="w", team="motor_control", kind="artifact_changed", description="BrkPedalPos",
              target_ids=["SIG-BrkPedalPos"], delivery="digest", created_by="sato",
              created_at=datetime(2026, 11, 1, tzinfo=JST))
    teams = [r.team for r in route_change(ev("e1", "SIG-BrkPedalPos", 10), graph, [w])]
    assert teams == [Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL]

def test_unknown_artifact_routes_nowhere(graph):
    assert route_change(ev("e1", "NOPE-9", 10), graph, []) == []

def test_non_agent_team_artifact_routes_nowhere(graph, dataset):
    battery = next(a for a in dataset.artifacts if a.team == Team.BATTERY_CONTROL)
    assert route_change(ev("e1", battery.id, 10), graph, []) == []

def test_same_event_twice_has_same_key(graph):
    a = route_change(ev("e1", "SIG-BrkPedalPos", 10), graph, [])[0]
    b = route_change(ev("e1", "SIG-BrkPedalPos", 10), graph, [])[0]
    assert a.id == b.id

def test_coalesce_merges_changes_within_window(graph):
    r1 = route_change(ev("e1", "SIG-BrkPedalPos", 10), graph, [])
    r2 = route_change(ev("e2", "SIG-BrkPedalPos", 12), graph, [])
    r3 = route_change(ev("e3", "SIG-BrkPedalPos", 30), graph, [])
    merged = coalesce(r1 + r2 + r3)
    assert sorted(m.source_ids for m in merged) == [["e1", "e2"], ["e3"]]
    first = next(m for m in merged if m.source_ids == ["e1", "e2"])
    assert first.not_before == datetime(2026, 11, 17, 21, 15, tzinfo=JST)
    assert first.id == idempotency_key(Team.INTEGRATED_CONTROL, "change", ["e1", "e2"])

def test_test_run_streak_routes_with_immediate_floor(graph):
    t0 = datetime(2026, 11, 18, 10, 0, tzinfo=JST)
    w = Watch(id="w1", team="integrated_control", kind="test_failure_streak", description="回生協調の HILS 失敗",
              feature="regen_coord", streak=3, delivery="immediate", created_by="tanaka", created_at=t0)
    runs = [TestRun(id=f"r{i}", testcase_id="TC-HILS-031", feature="regen_coord", result="fail",
                    executed_at=t0 + timedelta(hours=3 * i)) for i in range(3)]
    reqs = route_test_run(runs[-1], runs[:-1], graph, [w])
    assert [r.team for r in reqs] == [Team.INTEGRATED_CONTROL]
    assert reqs[0].floor == Classification.NOTIFY_NOW
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --directory core pytest tests/test_routing.py -v`
Expected: FAIL

- [ ] **Step 3: `routing.py` を実装する**

注意: 評価チームはテストの持ち主だが、`route_test_run` の宛先はリンク先モデルのチーム（回生協調なら統合制御）。評価チームのアシスタントへの解析依頼は、受け取ったアシスタントが `analysis_request` で出す（Plan 3）。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --directory core pytest tests/test_routing.py -v`
Expected: PASS（8 件）

- [ ] **Step 5: Commit**

```bash
git add core/src/vehicle_core/routing.py core/tests/test_routing.py
git commit -m "feat(core): 変更と試験結果の振り分け、冪等キー、まとめを追加"
```

---

### Task 8: 書き込み窓口の検査

**Files:**
- Create: `core/src/vehicle_core/gateway.py`
- Test: `core/tests/test_gateway.py`

**Interfaces:**
- Consumes: `CONTAINER_MODELS`, `AgentMail`, `MailKind`, `Message`, `MessageRole`, `Team`, `AGENT_TEAMS`, `VEHICLE_ID`
- Produces:
  - `class WriteDenied(Exception)`: 属性 `reason: str`（日本語の短い理由）
  - `AGENT_WRITABLE: frozenset[str] = {"messages", "proposals", "notifications", "agent_runs", "watches", "schedules", "agent_mail"}`
  - `AGENT_MAIL_ALLOWED: frozenset[MailKind] = {analysis_request, analysis_result, question, answer, human_reply, escalation}`
  - `def authorize_agent_write(caller_team: str | None, container: str, doc: dict, lookup_message: Callable[[str], Message | None]) -> BaseModel`: 許可なら検証済みのモデルを返す。拒否なら `WriteDenied`

規則（設計書 7.5 節、本計画の決定4）:
1. `caller_team` が `None`、`Team` にない値、`AGENT_TEAMS` にない → 拒否
2. `container` が `AGENT_WRITABLE` にない → 拒否（`artifacts`、`change_events`、`test_runs`、`team_settings` を含む）
3. `CONTAINER_MODELS[container].model_validate(doc)` が失敗 → 拒否
4. `vehicle_id != VEHICLE_ID` → 拒否
5. `agent_mail` 以外: `team != caller_team` → 拒否。`messages` は `role == assistant` 以外を拒否
6. `agent_mail`: `from_team != caller_team` → 拒否。`kind` が `AGENT_MAIL_ALLOWED` にない（＝`impact_notice`）→ 拒否。`to_team` が `AGENT_TEAMS` にない、または `to_team == caller_team` → 拒否。`escalation` は `to_team == chief_engineer` 以外を拒否
7. `human_reply`: `source_message_id` が `None`、`lookup_message` が `None` を返す、そのメッセージの `role != human`、またはその `team != caller_team` → 拒否

- [ ] **Step 1: 失敗するテストを書く**

```python
T = "2026-11-18T09:00:00+09:00"
HUMAN_MSG = Message(id="m-sato-1", team="motor_control", role="human", author="sato",
                    text="今週は v2.1 で手一杯で、R3 までに 20ms 対応は無理", created_at=T)
lookup = {"m-sato-1": HUMAN_MSG}.get

def mail(**kw):
    base = dict(id="am1", thread_id="th1", from_team="integrated_control", to_team="evaluation",
                kind="analysis_request", body="周期変更の応答を見て", created_at=T)
    return base | kw

def msg(**kw):
    return dict(id="m1", team="integrated_control", role="assistant", author="agent", text="x", created_at=T) | kw

@pytest.mark.parametrize("caller", [None, "", "unknown_team", "battery_control"])
def test_unknown_or_non_agent_caller_denied(caller):
    with pytest.raises(WriteDenied):
        authorize_agent_write(caller, "messages", msg(), lookup)

@pytest.mark.parametrize("container", ["artifacts", "change_events", "test_runs", "team_settings"])
def test_source_data_containers_denied(container):
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", container, {"id": "x"}, lookup)

def test_own_team_assistant_message_allowed():
    assert authorize_agent_write("integrated_control", "messages", msg(), lookup).id == "m1"

def test_other_team_message_denied():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "messages", msg(team="motor_control"), lookup)

def test_agent_cannot_write_human_message():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "messages", msg(role="human"), lookup)

def test_analysis_request_allowed():
    assert authorize_agent_write("integrated_control", "agent_mail", mail(), lookup).kind == MailKind.ANALYSIS_REQUEST

def test_impact_notice_denied_for_agents():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "agent_mail", mail(kind="impact_notice", to_team="motor_control"), lookup)

def test_spoofed_sender_denied():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "agent_mail", mail(from_team="motor_control"), lookup)

def test_escalation_only_to_chief():
    ok = mail(kind="escalation", to_team="chief_engineer")
    assert authorize_agent_write("integrated_control", "agent_mail", ok, lookup)
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "agent_mail", mail(kind="escalation", to_team="motor_control"), lookup)

def test_human_reply_requires_own_team_human_message():
    reply = mail(from_team="motor_control", to_team="integrated_control", kind="human_reply",
                 body="R3 までの対応は無理", stance="cannot", source_message_id="m-sato-1")
    assert authorize_agent_write("motor_control", "agent_mail", reply, lookup)
    with pytest.raises(WriteDenied):  # 他チームの人の発言を自チームの返事として使う
        authorize_agent_write("evaluation", "agent_mail", reply | {"from_team": "evaluation"}, lookup)
    with pytest.raises(WriteDenied):  # 元の発言がない
        authorize_agent_write("motor_control", "agent_mail", reply | {"source_message_id": None}, lookup)

def test_wrong_vehicle_denied():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "messages", msg(vehicle_id="other-car"), lookup)

def test_invalid_doc_denied():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "messages", {"id": "m1"}, lookup)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --directory core pytest tests/test_gateway.py -v`
Expected: FAIL

- [ ] **Step 3: `gateway.py` を実装する**

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --directory core pytest tests/test_gateway.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/vehicle_core/gateway.py core/tests/test_gateway.py
git commit -m "feat(core): エージェント用の書き込み窓口の検査を追加"
```

---

### Task 9: エスカレーションの判定

**Files:**
- Create: `core/src/vehicle_core/escalation.py`
- Test: `core/tests/test_escalation.py`

**Interfaces:**
- Consumes: `AgentMail`, `MailKind`, `Stance`, `REPLY_DEADLINE`, `to_jst`
- Produces:
  - `class EscalationDecision(BaseModel)`: `escalate: bool, reason: Literal["cannot", "no_reply"] | None`
  - `def needs_escalation(thread: Iterable[AgentMail], now: datetime) -> EscalationDecision`
    - スレッドにすでに `escalation` がある → `escalate=False`
    - `human_reply` で `stance == cannot` が1つでもある → `escalate=True, reason="cannot"`
    - `impact_notice` があり、その `to_team` からの `human_reply` が1つもなく、`now - impact_notice.created_at >= REPLY_DEADLINE` → `escalate=True, reason="no_reply"`
    - それ以外 → `escalate=False`

- [ ] **Step 1: 失敗するテストを書く**

```python
T0 = datetime(2026, 11, 18, 9, 0, tzinfo=JST)
NOTICE = AgentMail(id="n1", thread_id="th1", from_team="integrated_control", to_team="motor_control",
                   kind="impact_notice", body="BrkPedalPos 周期変更", created_at=T0)

def reply(stance, minutes=30):
    return AgentMail(id=f"r-{stance}", thread_id="th1", from_team="motor_control", to_team="integrated_control",
                     kind="human_reply", body="...", stance=stance, source_message_id="m-sato-1",
                     created_at=T0 + timedelta(minutes=minutes))

def test_cannot_reply_escalates():
    d = needs_escalation([NOTICE, reply("cannot")], T0 + timedelta(hours=1))
    assert d.escalate and d.reason == "cannot"

def test_can_reply_does_not_escalate():
    assert needs_escalation([NOTICE, reply("can")], T0 + timedelta(hours=1)).escalate is False

def test_no_reply_after_48h_escalates():
    assert needs_escalation([NOTICE], T0 + timedelta(hours=47, minutes=59)).escalate is False
    d = needs_escalation([NOTICE], T0 + timedelta(hours=48))
    assert d.escalate and d.reason == "no_reply"

def test_already_escalated_thread_does_not_escalate_again():
    esc = AgentMail(id="e1", thread_id="th1", from_team="integrated_control", to_team="chief_engineer",
                    kind="escalation", body="...", created_at=T0 + timedelta(hours=2))
    assert needs_escalation([NOTICE, reply("cannot"), esc], T0 + timedelta(hours=3)).escalate is False
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --directory core pytest tests/test_escalation.py -v`
Expected: FAIL

- [ ] **Step 3: `escalation.py` を実装する**

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --directory core pytest tests/test_escalation.py -v`
Expected: PASS（4 件）

- [ ] **Step 5: Commit**

```bash
git add core/src/vehicle_core/escalation.py core/tests/test_escalation.py
git commit -m "feat(core): エスカレーションの判定を追加"
```

---

### Task 10: デモのシナリオ定義と、コアだけで流す通しテスト

**Files:**
- Create: `core/src/vehicle_core/scenarios.py`
- Modify: `README.md`（「開発」節に core のテストの実行方法を1行追加）
- Test: `core/tests/test_scenarios.py`

**Interfaces:**
- Consumes: Task 1〜9 のすべて
- Produces:
  - `class StepKind(StrEnum)`: `set_clock`, `change`, `test_run`, `human_says`
  - `class ScenarioStep(BaseModel)`: `kind: StepKind, at: AwareDatetime, change: ChangeEvent | None = None, test_run: TestRun | None = None, team: Team | None = None, person_id: str | None = None, text: str | None = None, expect: dict[str, Any] = {}`
  - `class Scenario(BaseModel)`: `id: str, title_ja: str, steps: list[ScenarioStep]`
  - `SCENARIOS: dict[str, Scenario]`、`SCENARIO_ORDER: list[str] = ["s1_signal_period", "s5_watch_memory", "s2_hils_streak", "s0_noise", "s3_morning", "s4_release_gap"]`

シナリオの中身（設計書 5.3 節。日付は仮想の時計の値）:
- `s1_signal_period`「CAN 信号の周期変更」
  1. `change` 2026-11-17 21:10: `SIG-BrkPedalPos` の `attributes.period_ms` 10→20（changed_by `tanaka`）。`expect={"routed_teams": ["integrated_control"], "impacted_count": 8, "floor": "notify_now", "deliver_at": "2026-11-18T08:00:00+09:00"}`
  2. `set_clock` 2026-11-18 08:00
  3. `human_says` 2026-11-18 08:40、team `motor_control`、`sato`:「今週は v2.1 で手一杯で、R3 までに 20ms 対応は無理です」
  4. `human_says` 2026-11-18 08:50、team `integrated_control`、`tanaka`:「周期は CAN 負荷の都合で戻せません」
- `s5_watch_memory`「会話で見張りを頼む・忘れさせる」
  1. `human_says` 2026-11-18 09:10、`integrated_control`、`tanaka`:「回生協調の HILS が落ちたら、今後は朝を待たずにすぐ教えて」
  2. `human_says` 09:12、同:「連絡は朝まとめて」
  3. `human_says` 09:15、同:「さっきの『朝まとめて』は忘れて」
- `s2_hils_streak`「HILS の失敗傾向」
  1〜3. `test_run` 2026-11-18 10:00 / 13:00 / 16:00: `TC-HILS-031`、feature `regen_coord`、`fail`。3つ目に `expect={"requires_watch": "test_failure_streak:regen_coord", "routed_teams": ["integrated_control"], "floor": "notify_now"}`
- `s0_noise`「知らせるべきでない変更」
  1. `change` 2026-11-18 17:30: `SPEC-BRK-04` の `description` の誤字修正。`expect={"routed_teams": ["integrated_control"], "floor": "silent"}`
- `s3_morning`「朝のブリーフィング」
  1. `set_clock` 2026-11-19 08:00
- `s4_release_gap`「リリース前の抜け漏れチェック」
  1. `set_clock` 2026-11-23 08:00。`expect={"release_id": "R3", "unverified_requirements": 7, "open_reviews": 3, "unverified_safety": 2}`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_order_covers_all_scenarios():
    assert set(SCENARIO_ORDER) == set(SCENARIOS)

def test_steps_are_chronological_across_order():
    times = [s.at for sid in SCENARIO_ORDER for s in SCENARIOS[sid].steps]
    assert times == sorted(times)

def test_steps_reference_existing_artifacts_and_people(dataset):
    ids = {a.id for a in dataset.artifacts}
    people = {p.id for p in dataset.people}
    for sc in SCENARIOS.values():
        for st in sc.steps:
            if st.change:
                assert st.change.artifact_id in ids
            if st.test_run:
                assert st.test_run.testcase_id in ids
            if st.person_id:
                assert st.person_id in people

def test_core_expectations_hold_end_to_end(dataset):
    graph = Graph.from_artifacts(dataset.artifacts)
    settings = {s.team: s for s in dataset.team_settings}
    regen_watch = Watch(id="w-regen", team="integrated_control", kind="test_failure_streak",
                        description="回生協調の HILS 失敗", feature="regen_coord", streak=3,
                        delivery="immediate", created_by="tanaka", created_at=datetime(2026, 11, 18, 9, 10, tzinfo=JST))
    runs = list(dataset.test_runs)
    for sid in SCENARIO_ORDER:
        for st in SCENARIOS[sid].steps:
            watches = [regen_watch] if st.expect.get("requires_watch") else []
            if st.kind == StepKind.CHANGE:
                reqs = route_change(st.change, graph, watches)
            elif st.kind == StepKind.TEST_RUN:
                reqs = route_test_run(st.test_run, runs, graph, watches)
                runs.append(st.test_run)
            else:
                reqs = []
            e = st.expect
            if "routed_teams" in e:
                assert [r.team.value for r in reqs] == e["routed_teams"], (sid, st.at)
            if "floor" in e:
                assert reqs[0].floor.value == e["floor"]
            if "impacted_count" in e:
                assert len(reqs[0].impact.impacted_ids) == e["impacted_count"]
            if "deliver_at" in e:
                r = reqs[0]
                d = decide_delivery(r.floor, r.impact.touches_safety, st.at, settings[r.team])
                assert d.deliver_at.isoformat() == e["deliver_at"]
            if "release_id" in e:
                g = release_gaps(dataset, e["release_id"])
                assert (len(g.unverified_requirement_ids), len(g.open_review_ids), len(g.unverified_safety_ids)) \
                    == (e["unverified_requirements"], e["open_reviews"], e["unverified_safety"])
```

注意: `s4` の集計は `dataset` のシード時点の値で行う（`s2` の失敗を足すと `REQ-112` が未検証になり件数が変わる。それはシナリオの演出として Plan 4 で扱う）。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --directory core pytest tests/test_scenarios.py -v`
Expected: FAIL

- [ ] **Step 3: `scenarios.py` を上のとおり実装し、README の「状態」節の下に「開発」節を作って `uv run --directory core pytest` を書く**

- [ ] **Step 4: core のテストを全部流す**

Run: `uv run --directory core pytest -v`
Expected: すべて PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/vehicle_core/scenarios.py core/tests/test_scenarios.py README.md
git commit -m "feat(core): デモのシナリオ定義とコアの通しテストを追加"
```
