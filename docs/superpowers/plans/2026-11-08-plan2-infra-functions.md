# Plan 2: azd + Bicep の基盤と Azure Functions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `azd up` 1回で、Cosmos DB・Functions・Storage・Web PubSub・Application Insights と書き込み窓口用の Entra アプリ登録を作り、Functions が「変更の振り分け、まとめ、定時実行、メール配達、書き込み窓口、画面への通知」を `vehicle_core` を使って行う状態にする。エージェント本体（Plan 3）はまだ呼ばず、調査依頼を記録してログに出すところまで作る。

**Architecture:** uv ワークスペースに `functions/` を2つ目のメンバーとして足す。`function_app.py` のトリガーは1行で純粋な関数（`proactive_functions` パッケージ）に渡し、その関数は `Store`・`Clock`・`AgentInvoker`・`Publisher`・`TokenVerifier` を引数で受け取る。テストはこれらの偽物で動かし、Azure なしで通る。時刻はすべて Cosmos に置いた仮想時計（実時間＋ずれ）から取り、タイマーと「時計の変更」の両方が同じ `run_tick` を呼ぶ。

**Tech Stack:** Python 3.12、Azure Functions（Flex Consumption、Python v2 プログラミングモデル）、azure-cosmos、azure-identity、azure-messaging-webpubsubservice、PyJWT[crypto]、Bicep（Microsoft Graph 拡張 `microsoftgraph/v1.0:1.0.0`）、azd 1.37 以降、pytest

**Spec:** `docs/superpowers/specs/2026-11-07-proactive-vehicle-agent-design.md`（特に 6 章、7.2〜7.5 節、7.8 節、9 章、10 章）。前提: `docs/superpowers/plans/2026-11-07-plan1-vehicle-core.md`（末尾の「実装時の決定」を含む）

### 計画全体の中での位置づけ
| 計画 | 中身 |
|---|---|
| Plan 1（済） | `vehicle_core`: 判定ロジックと架空データ |
| **Plan 2（本書）** | azd + Bicep の基盤、Functions（振り分け、まとめ、定時実行、メール配達、書き込み窓口、画面への通知）、シード投入と仮想時計の操作 |
| Plan 3 | Foundry ホステッドエージェント4体、`AgentInvoker` の本物、Sandboxes |
| Plan 4 | Web アプリ（BFF と画面）、シナリオを進める仕組み、シナリオテスト |

## Global Constraints

- Python は 3.12（Flex Consumption の `runtime.version = "3.12"`、`requires-python = ">=3.12"`）
- 地域は `japaneast`。ホステッドエージェント、Foundry Memory、Container Apps Sandboxes、Flex Consumption、Web PubSub がすべて使えることを 2026-11-08 に確認した（設計書 6.3 節）
- キーと接続文字列を使わない（設計書 10 章）: Cosmos は `disableLocalAuth: true`、Storage は `allowSharedKeyAccess: false`、Web PubSub は `disableLocalAuth: true`、Application Insights は `DisableLocalAuth: true`（Functions は `APPLICATIONINSIGHTS_AUTHENTICATION_STRING` で Entra 認証）。HTTP 関数は `AuthLevel.ANONYMOUS` にし、関数キーは使わず、コードで Entra のトークンを検証する
- 使わないときの費用をほぼゼロにする（設計書 2.1 節 6）: Cosmos はサーバーレス、Functions は Flex Consumption（常時準備のインスタンスなし）、Web PubSub は `Free_F1`、Storage は `Standard_LRS`
- データベース名 `proactive`。パーティションキーは `leases` だけ `/id`、ほかはすべて `/vehicle_id`（Plan 1 の決定）
- Functions の中の現在時刻は、必ず仮想時計（`StoredClock`）から取る。`datetime.now()` を直接呼ばない
- 書き込み窓口は `authorize_agent_write` が返したモデルを、新規作成で保存する（既存の ID は上書きしない。Plan 1 の申し送り）
- 画面に出る文字列と、窓口が返す拒否の理由は日本語
- `azd provision`・`azd up`・`azd down` と Azure 上のデータを消す操作は、実行の前に制作者に確認する（費用と外部への副作用があるため）
- 登場するデータはすべて架空

### 設計書の隙間を埋めた決定（実装者はこのとおりに作る）
1. **仮想時計**: Cosmos の `system` コンテナーに `{"id": "clock", "vehicle_id": "kakuu-suv", "offset_seconds": <float>, "updated_at": <ISO>}` を1件置く。現在時刻 = 実時間 + `offset_seconds`。時計を合わせる操作は「ずれ」を書き換える。時間は実時間と同じ速さで流れ続ける（まとめの窓 180 秒が実時間で過ぎる）
2. **tick のきっかけ**: 1分ごとのタイマーと、`system` コンテナーの変更フィード（時計を合わせた直後）の両方が `run_tick` を呼ぶ。HTTP の管理用エンドポイントは作らない（キーを使わずに守る手間を省く。Plan 4 のシナリオ再生も時計の文書を書くだけでよい）
3. **調査依頼の保存先**: `investigations` コンテナーを足す（設計書 7.2 節の表にない）。ID は冪等キーで、新規作成のみ。同じ変更が二度届いても 409 で1件にとどまる。`not_before` を過ぎたものを tick が `coalesce` してから渡す
4. **エージェントへの受け渡し**: `AgentInvoker` プロトコル（`invoke(request) -> None`）の境目だけ作り、本書ではログに出すだけの `LoggingInvoker` を使う。本物は Plan 3
5. **統括エージェントへの写し**: すべてのメールで統括エージェントを起動はしない（LLM の費用が増え、設計書 4.2 節の「前に出るのは条件を満たしたときだけ」と合わない）。統括エージェントは読み取り権限で `agent_mail` を読める。これを「写し」とする。起動するのは、統括宛ての `escalation` などのメールが来たときと、定時の仕事のときだけ
6. **メールで起動するときの下限**: `impact_notice` と `escalation` は `notify_now`（人の承認を経た連絡と、判断の依頼なので）。ほかの種類は `silent`（エージェントどうしの内部のやり取り）
7. **返事の期限切れ**: tick が `impact_notice` のあるスレッドごとに `needs_escalation` を調べ、理由が `no_reply` なら、連絡を出したチーム（最初の `impact_notice` の `from_team`）のアシスタントへ依頼を出す。理由が `cannot` の場合は `human_reply` のメール配達で起動されるので、tick では扱わない
8. **配達時刻はコードが決める**: 窓口は、エージェントが書いた `Notification` の `deliver_at` を `decide_delivery`（分類、安全要求に関わるか、チームの設定、現在時刻）で置き換える。安全要求に関わるかは、`origin_artifact_id` から `analyze_impact` で求める。`deliver_at` が現在時刻以前なら、その場で `delivered_at = now` にする。後の時刻なら tick がその時刻に `delivered_at` を付ける
9. **画面への通知**: Web PubSub には「再読み込みの合図」だけを送る: `{"type": "refresh", "kind": <コンテナー名>, "id": <文書 ID>, "team": <チーム>}`。グループ名はチームの値（例: `integrated_control`）。同じ合図が二度届いても害はない（画面が読み直すだけ）。配達前の `Notification` と、それにひもづく `Message` は合図を送らない
10. **書き込み窓口の呼び出し元**: トークンの `azp`（v1 トークンなら `appid`）を、`team_settings` の `agent_client_id` と照らしてチームを決める。Plan 3 がエージェントを作ったあと、Functions を再デプロイせずに対応表を埋められる。`roles` は見ない（既定ではテナント内のどのアプリもこの API のトークンを取れるので、許可の根拠は対応表だけにする）
11. **窓口で上書きしてよいもの**: 自チームの `agent_runs` の置き換え（作業の「いま → 完了」の更新に要る）と、自チームの `watches` の削除（「忘れて」に要る）だけ。ほかは新規作成のみ
12. **シード由来の文書**: シード投入とリセットで書く文書には `"origin": "seed"` を付け、変更フィードの処理は飛ばす（シードの試験結果 26 件でエージェントが一斉に起動するのを防ぐ）。シードの投入は、リセットなしなら足りない文書だけを作り、リセットありならすべて消してから作り直す。リセットでも `team_settings` の `agent_client_id` は引き継ぐ
13. **毎日の予定**: 定時の仕事を実行したら `done_at` を付け、`payload.recur == "daily"` なら次の回を作る。次の回の時刻は「同じ時刻で、現在時刻より後の最初の日」。時計を数日進めても、たまった日数分は動かない
14. **パッケージング**: デプロイ前の azd フックで `core/src/vehicle_core` を `functions/vehicle_core` に写し、`uv export` で `functions/requirements.txt` を作る。デプロイ後のフックで写しを消す。どちらも `.gitignore` に入れる
15. **ローカルでの Functions の起動**: Cosmos のエミュレーターは使わない（Entra 認証がない）。`func start` は、`az login` した自分の ID で Azure 上の Cosmos につなぐ。タスクの合否はすべて偽物を使った単体テストで決め、Azure 上での確認は最後のタスクのスモークテストで行う

## Review Focus

1. **同じ変更フィードのバッチが二度届く**（Functions の再試行で起こる）→ 調査依頼は1件のまま。テストは Task 5 に入れる
2. **シードの投入やリセットの文書が変更フィードに流れる** → 調査依頼は出ない。テストは Task 5 に入れる
3. **仮想時計を数日先へ進める**（シナリオ s4 で 11/19 → 11/23）→ 毎日の予定は1回だけ動き、次の回は現在時刻より後の 8:00 になる。テストは Task 6 に入れる
4. **タイマーと時計の変更で tick が同時に走る** → 同じ依頼がエージェントに渡るのは1回だけ。テストは Task 4 に入れる
5. **形の壊れた文書が変更フィードに来る**（手でデータを書き換えたときなど）→ その文書だけ飛ばしてログに残し、同じバッチの残りは処理する（例外を出すと同じバッチが永久に再試行される）。テストは Task 5 に入れる

---

## ファイル構成

```
pyproject.toml                      # members = ["core", "functions"]
azure.yaml                          # azd: functions サービスとフック
infra/
  main.bicep                        # サブスクリプションスコープ。リソースグループと各モジュール
  main.parameters.json
  bicepconfig.json                  # Microsoft Graph 拡張
  modules/
    monitoring.bicep                # Log Analytics、Application Insights
    storage.bicep                   # Functions 用と Blob（hils-logs、analysis-artifacts）
    cosmos.bicep                    # アカウント、DB、コンテナー、データのロール
    webpubsub.bicep
    functions.bicep                 # Flex Consumption のプランとアプリ、マネージド ID、ロール
    gateway-app.bicep               # 書き込み窓口の Entra アプリ登録（Graph 拡張）
functions/
  pyproject.toml                    # name = "proactive-functions"
  host.json
  .funcignore
  function_app.py                   # トリガーの定義だけ（1行で下へ渡す）
  proactive_functions/
    __init__.py
    settings.py                     # 環境変数
    store.py                        # Store プロトコル、CosmosStore、Conflict、NotFound
    clock.py                        # StoredClock、set_virtual_now
    investigations.py               # InvestigationRecord、enqueue、dispatch_due、AgentInvoker、LoggingInvoker
    handlers.py                     # 変更フィードの処理（変更、試験結果、メール）
    tick.py                         # run_tick（配達、定時の仕事、返事の期限切れ、受け渡し）
    auth.py                         # TokenVerifier、EntraTokenVerifier、AuthError
    gateway_http.py                 # 書き込み窓口の HTTP 処理
    publisher.py                    # Publisher、WebPubSubPublisher、publish_changes
    seeding.py                      # seed_store
  tests/
    fakes.py                        # MemoryStore、RecordingInvoker、RecordingPublisher、FakeVerifier
    conftest.py
    test_store_contract.py  test_clock.py  test_investigations.py  test_handlers.py
    test_tick.py  test_auth.py  test_gateway_http.py  test_publisher.py  test_seeding.py
    test_function_app.py
scripts/
  package_functions.py              # prepare / cleanup（azd フックから）
  seed.py                           # シード投入（--reset）
  clock.py                          # 仮想時計の表示と設定
  smoke.py                          # Azure 上のスモークテスト
core/src/vehicle_core/models.py     # 項目を3つ足す（Task 1）
core/src/vehicle_core/gateway.py    # 配達済み・完了済みの書き込みを拒否（Task 1）
core/src/vehicle_core/seed.py       # build_schedules（Task 1）
```

テストの実行: core は `uv run --directory core pytest`、Functions は `uv run --directory functions pytest`。

---

### Task 1: core に足すもの（配達済み、完了済み、エージェントの client ID、定時の仕事のシード）

**Files:**
- Modify: `core/src/vehicle_core/models.py`、`core/src/vehicle_core/gateway.py`、`core/src/vehicle_core/seed.py`
- Test: `core/tests/test_models.py`、`core/tests/test_gateway.py`、`core/tests/test_seed.py`

**Interfaces:**
- Produces:
  - `Notification.delivered_at: AwareDatetime | None = None`
  - `Schedule.done_at: AwareDatetime | None = None`
  - `TeamSettings.agent_client_id: str | None = None`
  - `authorize_agent_write`: `Notification` で `delivered_at` が空でない、または `Schedule` で `done_at` が空でないものを `WriteDenied("配達済みや完了済みの印はコードが付けます")` で拒否
  - `seed.build_schedules(dataset: Dataset) -> list[Schedule]`

`build_schedules` が返すもの（`first = next_time_at(SEED_NOW, DIGEST_TIME)` ＝ 2026-11-18 08:00 JST）:
- `integrated_control`、`motor_control`、`evaluation` ごとに `Schedule(id=f"sch-digest-{team}-20261118", team=team, due_at=first, task="morning_digest", payload={"recur": "daily", "series": f"sch-digest-{team}"})`
- `chief_engineer` に `Schedule(id="sch-briefing-chief_engineer-20261118", task="morning_briefing", due_at=first, payload={"recur": "daily", "series": "sch-briefing-chief_engineer"})`
- `chief_engineer` に `Schedule(id="sch-release-gap-R3", task="release_gap_check", due_at=<R3 の attributes.due_date の 7 日前の 08:00 JST>, payload={"release_id": "R3"})`

- [ ] **Step 1: 失敗するテストを書く**

```python
# core/tests/test_seed.py に追加
def test_build_schedules_daily_and_release_check(dataset):
    sch = {s.id: s for s in build_schedules(dataset)}
    assert len(sch) == 5
    d = sch["sch-digest-integrated_control-20261118"]
    assert d.due_at == datetime(2026, 11, 18, 8, 0, tzinfo=JST) and d.payload["recur"] == "daily"
    assert sch["sch-briefing-chief_engineer-20261118"].task == "morning_briefing"
    gap = sch["sch-release-gap-R3"]
    assert gap.team == Team.CHIEF_ENGINEER and gap.due_at == datetime(2026, 11, 23, 8, 0, tzinfo=JST)
    assert all(s.done_at is None for s in sch.values())

# core/tests/test_gateway.py に追加
def test_agent_cannot_mark_notification_delivered():
    doc = dict(id="n9", team="integrated_control", origin_artifact_id="SIG-BrkPedalPos", impacted_ids=[],
               highlight_ids=[], cross_team_edges=[], classification="notify_now", deliver_at=T,
               delivered_at=T, reason="r", created_at=T)
    with pytest.raises(WriteDenied):
        aw("integrated_control", "notifications", doc, lookup)
    assert aw("integrated_control", "notifications", doc | {"delivered_at": None}, lookup).id == "n9"

def test_agent_cannot_mark_schedule_done():
    doc = dict(id="s1", team="integrated_control", due_at=T, task="recheck", done_at=T)
    with pytest.raises(WriteDenied):
        aw("integrated_control", "schedules", doc, lookup)
    assert aw("integrated_control", "schedules", doc | {"done_at": None}, lookup).id == "s1"

# core/tests/test_models.py に追加
def test_team_settings_agent_client_id_defaults_to_none():
    assert TeamSettings(id="ts-x", team="evaluation").agent_client_id is None
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory core pytest -v -k "schedules or delivered or schedule_done or agent_client_id"` / Expected: FAIL（`build_schedules` がない、拒否されない、属性がない）
- [ ] **Step 3: 実装する** — 上の Interfaces のとおり。`build_schedules` は `next_time_at` と `release_ids` を持つ `R3` の `attributes["due_date"]`（`"2026-11-30"`）から求める
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory core pytest` / Expected: すべて PASS（99 件＋新しいテスト）
- [ ] **Step 5: Commit**

```bash
git add core/
git commit -m "feat(core): 配達済み・完了済みの印、エージェントの client ID、定時の仕事のシードを追加"
```

---

### Task 2: Functions の骨組み、パッケージング、基盤（Bicep）、最初のデプロイ

最初に一番危ないところ（`vehicle_core` を Flex Consumption に載せて import できるか）を確かめる。

**Files:**
- Modify: `pyproject.toml`（`members = ["core", "functions"]`）、`.gitignore`（`functions/vehicle_core/`、`functions/requirements.txt`、`.azure/` は既存）
- Create: `functions/pyproject.toml`、`functions/host.json`、`functions/.funcignore`、`functions/function_app.py`、`functions/proactive_functions/__init__.py`、`functions/tests/test_function_app.py`、`scripts/package_functions.py`、`azure.yaml`、`infra/` 一式

**Interfaces:**
- Produces:
  - `functions/pyproject.toml`: `name = "proactive-functions"`、`requires-python = ">=3.12"`、依存 `azure-functions>=1.21`、`azure-cosmos>=4.9`、`azure-identity>=1.19`、`azure-messaging-webpubsubservice>=1.2`、`pyjwt[crypto]>=2.9`、`vehicle-core`（`[tool.uv.sources] vehicle-core = { workspace = true }`）、開発用 `pytest>=8`。hatch の `packages = ["proactive_functions"]`、pytest の `testpaths = ["tests"]`、`pythonpath = ["."]`（`function_app` を import するため）
  - `GET /api/health`（匿名）→ `200 {"ok": true, "vehicle_id": "kakuu-suv"}`（`vehicle_core.constants.VEHICLE_ID` を返す。import できた証拠）
  - `scripts/package_functions.py prepare`: `core/src/vehicle_core` を `functions/vehicle_core` に写し、`uv export --package proactive-functions --no-dev --no-hashes --no-emit-workspace --frozen -o functions/requirements.txt` を実行する。`cleanup`: 写しを消す。パスはスクリプト自身の場所から求める（実行時のカレントディレクトリに依存しない）
  - azd の出力（`azd env get-values` で見える）: `AZURE_LOCATION`、`AZURE_RESOURCE_GROUP`、`COSMOS_ENDPOINT`、`COSMOS_DATABASE`、`FUNCTION_APP_NAME`、`FUNCTION_APP_URL`、`WEBPUBSUB_ENDPOINT`、`WEBPUBSUB_HUB`、`GATEWAY_APP_ID`、`GATEWAY_APP_ID_URI`、`AZURE_STORAGE_BLOB_ENDPOINT`、`APPLICATIONINSIGHTS_CONNECTION_STRING`

`azure.yaml`:
```yaml
name: proactive-agent
services:
  functions:
    project: ./functions
    language: python
    host: function
    hooks:
      prepackage:
        run: uv run python ../scripts/package_functions.py prepare
      postpackage:
        run: uv run python ../scripts/package_functions.py cleanup
hooks:
  postprovision:
    run: uv run --package proactive-functions python scripts/seed.py
```
（`scripts/seed.py` は Task 9 で作る。それまでは `postprovision` を書かない）

Bicep（`infra/`）で作るもの。名前は azd の慣例どおり `resourceToken = toLower(uniqueString(subscription().id, environmentName, location))` から作る。全リソースに `azd-env-name` タグ、Functions に `azd-service-name: functions` タグ:

| モジュール | リソースと主な設定 |
|---|---|
| `monitoring` | Log Analytics（`PerGB2018`、保持 30 日）、Application Insights（`DisableLocalAuth: true`） |
| `storage` | `Standard_LRS`、`allowSharedKeyAccess: false`、`allowBlobPublicAccess: false`、`minimumTlsVersion: TLS1_2`。Blob コンテナー `app-package`（Functions のデプロイ先）、`hils-logs`、`analysis-artifacts` |
| `cosmos` | `EnableServerless`、`disableLocalAuth: true`、整合性 `Session`。DB `proactive`。コンテナー `artifacts`、`change_events`、`test_runs`、`watches`、`messages`、`proposals`、`agent_mail`、`notifications`、`agent_runs`、`schedules`、`team_settings`、`investigations`、`system`（`/vehicle_id`）、`leases`（`/id`）。`sqlRoleAssignments` で組み込みの Data Contributor（`00000000-0000-0000-0000-000000000002`）を Functions のマネージド ID と `principalId`（デプロイする人）に付与 |
| `webpubsub` | `Free_F1`、`disableLocalAuth: true`。Functions のマネージド ID に `Web PubSub Service Owner` |
| `functions` | ユーザー割り当てマネージド ID 1つ。プラン `FC1`（`FlexConsumption`、`reserved: true`）。アプリ `kind: functionapp,linux`、`functionAppConfig.runtime = {name: python, version: '3.12'}`、`scaleAndConcurrency = {maximumInstanceCount: 40, instanceMemoryMB: 2048}`、デプロイ先は `app-package` コンテナー（認証はユーザー割り当て ID）。ロール: Storage Blob Data Owner、Storage Queue Data Contributor、Storage Table Data Contributor（ストレージ）、Monitoring Metrics Publisher（Application Insights） |
| `gateway-app` | `Microsoft.Graph/applications@v1.0`: `uniqueName: 'proactive-gateway-${resourceToken}'`、`signInAudience: 'AzureADMyOrg'`、`identifierUris: ['api://${tenant().tenantId}/proactive-gateway-${resourceToken}']`、`api.requestedAccessTokenVersion: 2`。対になる `Microsoft.Graph/servicePrincipals@v1.0` |

Functions のアプリ設定（キーなし）:
`AzureWebJobsStorage__credential=managedidentity`、`AzureWebJobsStorage__clientId`、`AzureWebJobsStorage__blobServiceUri`、`AzureWebJobsStorage__queueServiceUri`、`AzureWebJobsStorage__tableServiceUri`、`COSMOS__accountEndpoint`、`COSMOS__credential=managedidentity`、`COSMOS__clientId`（トリガー用の接続名 `COSMOS`）、`COSMOS_ENDPOINT`、`COSMOS_DATABASE=proactive`、`WEBPUBSUB_ENDPOINT`、`WEBPUBSUB_HUB=proactive`、`GATEWAY_TENANT_ID`、`GATEWAY_AUDIENCES=<appId>,<identifierUri>`、`AGENT_INVOKER=log`、`AZURE_CLIENT_ID=<マネージド ID の clientId>`（コードの `DefaultAzureCredential` 用）、`APPLICATIONINSIGHTS_CONNECTION_STRING`、`APPLICATIONINSIGHTS_AUTHENTICATION_STRING=ClientId=<clientId>;Authorization=AAD`

`infra/bicepconfig.json`:
```json
{ "extensions": { "microsoftGraphV1": "br:mcr.microsoft.com/bicep/extensions/microsoftgraph/v1.0:1.0.0" } }
```

- [ ] **Step 1: 失敗するテストを書く**

```python
# functions/tests/test_function_app.py
import json
import azure.functions as func

def test_health_returns_vehicle_id():
    import function_app
    resp = function_app._health()
    assert resp.status_code == 200
    assert json.loads(resp.get_body()) == {"ok": True, "vehicle_id": "kakuu-suv"}
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv sync --all-packages && uv run --directory functions pytest -v` / Expected: FAIL（`function_app` がない）
- [ ] **Step 3: 実装する** — `function_app.py` に `app = func.FunctionApp()` と、本体 `_health() -> func.HttpResponse`、それを呼ぶだけの `health`（`@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)`）。以後の関数も同じく「decorator 付きの関数は本体を呼ぶだけ」にする（decorator を付けた関数はテストから直接呼べないため）。`functions/tests/__init__.py` を空で作る（テストが `tests.fakes` を import するため）
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -v && uv run --directory core pytest -q` / Expected: PASS
- [ ] **Step 5: パッケージングを確かめる** — Run: `uv run python scripts/package_functions.py prepare` / Expected: `functions/vehicle_core/constants.py` と `functions/requirements.txt` ができ、`requirements.txt` に `azure-functions` があり `vehicle-core` と `proactive-functions` がない。続けて `uv run python scripts/package_functions.py cleanup` で `functions/vehicle_core/` が消える。`git status` に両方とも出ない
- [ ] **Step 6: Bicep を検査する** — Run: `az bicep build --file infra/main.bicep --stdout > /dev/null` / Expected: エラーなし（警告は読んで、意味のあるものは直す）
- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .gitignore azure.yaml infra/ functions/ scripts/package_functions.py
git commit -m "feat(infra): Functions の骨組み、パッケージング、Bicep の基盤を追加"
```

- [ ] **Step 8: 【制作者に確認してから】デプロイする** — 制作者に「`azd up` で japaneast にリソースを作ります（使わないときの費用はほぼゼロ。Entra のアプリ登録を1つ作ります）。進めてよいですか」と確認する。了承を得たら:
  Run: `azd env new proactive-dev --location japaneast`（既にあれば `azd env select`）、`azd up`
  Expected: 成功。`curl "$(azd env get-value FUNCTION_APP_URL)/api/health"` が `{"ok": true, "vehicle_id": "kakuu-suv"}`。失敗したら、原因（パッケージング、ロールの反映待ち、Graph の権限）を突き止めてから先へ進む。ロールの反映待ちで失敗したときは、数分待って `azd up` をやり直す
- [ ] **Step 9: 結果を記録する** — デプロイで直したことがあれば Commit する（`git commit -m "fix(infra): ..."`）

---

### Task 3: Store と仮想時計

**Files:**
- Create: `functions/proactive_functions/store.py`、`functions/proactive_functions/clock.py`、`functions/tests/fakes.py`、`functions/tests/conftest.py`
- Test: `functions/tests/test_store_contract.py`、`functions/tests/test_clock.py`

**Interfaces:**
- Produces（`store.py`）:
  - `class Conflict(Exception)`（ID が既にある、または etag が合わない）、`class NotFound(Exception)`
  - `class Store(Protocol)`:
    - `get(container: str, id: str) -> dict | None`
    - `create(container: str, doc: dict) -> dict`（既にあれば `Conflict`）
    - `upsert(container: str, doc: dict) -> dict`（シード投入だけが使う）
    - `replace(container: str, doc: dict, *, etag: str) -> dict`（etag が違えば `Conflict`、なければ `NotFound`）
    - `delete(container: str, id: str) -> None`（なければ `NotFound`）
    - `query(container: str, where: dict[str, Any] | None = None) -> list[dict]`（等号の AND。値が `None` の条件は「項目がない、または null」）
    - 返す文書には `_etag` が入る。すべての文書は `vehicle_id` を持ち、パーティションキーは `VEHICLE_ID`
  - `class CosmosStore(Store)`: `__init__(endpoint: str, database: str, credential)`。`azure.cosmos` の `create_item` / `upsert_item` / `replace_item(etag=..., match_condition=MatchConditions.IfNotModified)` / `read_item` / `delete_item` / `query_items(partition_key=VEHICLE_ID)`。`CosmosResourceExistsError` と `CosmosAccessConditionFailedError` は `Conflict`、`CosmosResourceNotFoundError` は `None` か `NotFound`
- Produces（`clock.py`）:
  - `class StoredClock`: `__init__(store: Store, system: Clock = SystemClock())`、`now() -> datetime`（JST）
  - `def set_virtual_now(store: Store, target: datetime, system_now: datetime) -> None`（`offset_seconds = (target - system_now).total_seconds()` を `system/clock` に upsert）
- Produces（`tests/fakes.py`）: `class MemoryStore(Store)`（`_etag` は書くたびに変わる連番の文字列）

- [ ] **Step 1: 失敗するテストを書く**

```python
# functions/tests/test_store_contract.py
# 同じ契約を MemoryStore と（環境変数 COSMOS_TEST_ENDPOINT があれば）CosmosStore で確かめる
import os, pytest
from proactive_functions.store import Conflict, NotFound
from tests.fakes import MemoryStore

def _stores():
    yield pytest.param(MemoryStore(), id="memory")
    if os.environ.get("COSMOS_TEST_ENDPOINT"):
        from azure.identity import DefaultAzureCredential
        from proactive_functions.store import CosmosStore
        yield pytest.param(CosmosStore(os.environ["COSMOS_TEST_ENDPOINT"], "proactive", DefaultAzureCredential()), id="cosmos")

@pytest.fixture(params=list(_stores()))
def store(request):
    return request.param

def doc(id_, **kw):
    return {"id": id_, "vehicle_id": "kakuu-suv", **kw}

def test_create_twice_conflicts(store):
    store.create("investigations", doc("t-c1"))
    with pytest.raises(Conflict):
        store.create("investigations", doc("t-c1"))
    store.delete("investigations", "t-c1")

def test_replace_with_stale_etag_conflicts(store):
    first = store.create("investigations", doc("t-r1", status="pending"))
    store.replace("investigations", {**first, "status": "dispatched"}, etag=first["_etag"])
    with pytest.raises(Conflict):
        store.replace("investigations", {**first, "status": "merged"}, etag=first["_etag"])
    store.delete("investigations", "t-r1")

def test_query_none_matches_missing_or_null(store):
    store.create("notifications", doc("t-q1", delivered_at=None))
    store.create("notifications", doc("t-q2"))
    store.create("notifications", doc("t-q3", delivered_at="2026-11-18T08:00:00+09:00"))
    ids = {d["id"] for d in store.query("notifications", {"delivered_at": None})}
    assert {"t-q1", "t-q2"} <= ids and "t-q3" not in ids
    for i in ("t-q1", "t-q2", "t-q3"):
        store.delete("notifications", i)

def test_get_missing_returns_none_and_delete_missing_raises(store):
    assert store.get("investigations", "t-none") is None
    with pytest.raises(NotFound):
        store.delete("investigations", "t-none")

# functions/tests/test_clock.py
def test_stored_clock_applies_offset():
    store = MemoryStore()
    real = VirtualClock(datetime(2026, 11, 8, 12, 0, tzinfo=JST))
    set_virtual_now(store, datetime(2026, 11, 17, 21, 10, tzinfo=JST), real.now())
    clock = StoredClock(store, real)
    assert clock.now() == datetime(2026, 11, 17, 21, 10, tzinfo=JST)
    real.advance(timedelta(minutes=4))                     # 実時間が流れると仮想時計も流れる
    assert clock.now() == datetime(2026, 11, 17, 21, 14, tzinfo=JST)

def test_stored_clock_without_document_is_real_time():
    real = VirtualClock(datetime(2026, 11, 8, 12, 0, tzinfo=JST))
    assert StoredClock(MemoryStore(), real).now() == real.now()
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_store_contract.py tests/test_clock.py -v` / Expected: FAIL（モジュールがない）
- [ ] **Step 3: 実装する**
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -v` / Expected: PASS（`cosmos` のパラメーターは環境変数がないので出ない）
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): Store と仮想時計を追加"`

---

### Task 4: 調査依頼の記録と受け渡し

**Files:**
- Create: `functions/proactive_functions/investigations.py`
- Modify: `functions/tests/fakes.py`（`RecordingInvoker`）
- Test: `functions/tests/test_investigations.py`

**Interfaces:**
- Consumes: `InvestigationRequest`、`coalesce`（`vehicle_core.routing`）、`Store`、`Conflict`
- Produces:
  - `class InvestigationRecord(InvestigationRequest)`: `status: Literal["pending", "dispatched", "merged", "failed"] = "pending"`、`merged_into: str | None = None`、`dispatched_at: AwareDatetime | None = None`、`error: str | None = None`
  - `class AgentInvoker(Protocol): def invoke(self, request: InvestigationRequest) -> None`
  - `class LoggingInvoker(AgentInvoker)`: `logging.info` に `team`、`trigger`、`id`、`source_ids` を出すだけ
  - `def enqueue(store: Store, requests: Iterable[InvestigationRequest]) -> list[str]`: `pending` として新規作成。`Conflict` は黙って飛ばす。新しく作れた ID だけ返す
  - `def dispatch_due(store: Store, invoker: AgentInvoker, now: datetime) -> list[str]`: 渡した依頼の ID を返す

`dispatch_due` の手順:
1. `status == "pending"` の記録を読み、`InvestigationRequest` にして `coalesce` する
2. まとめた結果ごとに、`not_before <= now` のものだけ扱う（まとめに入った変更の最後のものが窓を過ぎるまで待つことになる）
3. 元の記録を1件ずつ etag 付きで置き換えて「確保」する。1件だけなら `status="dispatched"`、`dispatched_at=now`。複数をまとめたなら元の記録は `status="merged"`、`merged_into=<まとめた ID>`。確保で `Conflict` が出たら、そのまとまりは別の tick が扱ったとみなして飛ばす
4. 複数をまとめたときは、まとめた ID で `status="dispatched"` の記録を新規作成する（`Conflict` は飛ばす）
5. `invoker.invoke(まとめた依頼)`。例外が出たら、その記録を `status="failed"`、`error=str(例外)` にする（再試行はしない）

- [ ] **Step 1: 失敗するテストを書く**

```python
def req(id_, source, not_before, trigger="change", origin="SIG-BrkPedalPos", team="integrated_control"):
    return InvestigationRequest(id=id_, team=team, trigger=trigger, origin_artifact_id=origin,
                                source_ids=[source], impact=None, matched_watch_ids=[], floor="notify_now",
                                not_before=not_before)

T0 = datetime(2026, 11, 17, 21, 13, tzinfo=JST)

def test_enqueue_is_idempotent():
    store = MemoryStore()
    assert enqueue(store, [req("k1", "ce-1", T0)]) == ["k1"]
    assert enqueue(store, [req("k1", "ce-1", T0)]) == []
    assert len(store.query("investigations")) == 1

def test_not_due_is_not_dispatched():
    store, inv = MemoryStore(), RecordingInvoker()
    enqueue(store, [req("k1", "ce-1", T0)])
    assert dispatch_due(store, inv, T0 - timedelta(seconds=1)) == []
    assert inv.calls == []

def test_due_single_request_dispatched_once():
    store, inv = MemoryStore(), RecordingInvoker()
    enqueue(store, [req("k1", "ce-1", T0)])
    assert dispatch_due(store, inv, T0) == ["k1"]
    assert dispatch_due(store, inv, T0 + timedelta(minutes=1)) == []
    assert [c.id for c in inv.calls] == ["k1"]
    assert store.get("investigations", "k1")["status"] == "dispatched"

def test_close_changes_are_merged_and_wait_for_the_last():
    store, inv = MemoryStore(), RecordingInvoker()
    enqueue(store, [req("k1", "ce-1", T0), req("k2", "ce-2", T0 + timedelta(seconds=60))])
    assert dispatch_due(store, inv, T0 + timedelta(seconds=30)) == []          # 2件目の窓がまだ
    [merged_id] = dispatch_due(store, inv, T0 + timedelta(seconds=60))
    assert inv.calls[0].source_ids == ["ce-1", "ce-2"]
    assert {store.get("investigations", k)["status"] for k in ("k1", "k2")} == {"merged"}
    assert store.get("investigations", merged_id)["status"] == "dispatched"

def test_concurrent_tick_loses_claim_and_skips():
    # Review Focus 4: 確保の直前に別の tick が同じ記録を書き換えた
    store, inv = MemoryStore(), RecordingInvoker()
    enqueue(store, [req("k1", "ce-1", T0)])
    store.before_replace = lambda c, d: store.touch(c, d["id"])   # 置き換えの直前に etag を変える
    assert dispatch_due(store, inv, T0) == []
    assert inv.calls == []

def test_invoker_failure_is_recorded():
    store = MemoryStore()
    enqueue(store, [req("k1", "ce-1", T0)])
    dispatch_due(store, RecordingInvoker(fail=True), T0)
    rec = store.get("investigations", "k1")
    assert rec["status"] == "failed" and rec["error"]
```
（`MemoryStore.before_replace` と `touch(container, id)` は、競合を作るためのテスト用のつまみ。`fakes.py` に置く）

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_investigations.py -v` / Expected: FAIL
- [ ] **Step 3: 実装する**
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -v` / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): 調査依頼の記録、まとめ、エージェントへの受け渡しを追加"`

---

### Task 5: 変更フィードの処理（変更、試験結果、メール）

**Files:**
- Create: `functions/proactive_functions/handlers.py`
- Test: `functions/tests/test_handlers.py`

**Interfaces:**
- Consumes: `Graph`、`route_change`、`route_test_run`、`idempotency_key`、`ChangeEvent`、`TestRun`、`AgentMail`、`Watch`、`Artifact`、`enqueue`
- Produces:
  - `def handle_change_events(docs: list[dict], store: Store) -> list[str]`
  - `def handle_test_runs(docs: list[dict], store: Store) -> list[str]`
  - `def handle_agent_mail(docs: list[dict], store: Store) -> list[str]`
  - `def mail_request(mail: AgentMail) -> InvestigationRequest | None`（宛先がエージェントのいないチームなら `None`）
  - どれも新しく記録した調査依頼の ID を返す

共通の規則: `doc.get("origin") == "seed"` は飛ばす。`model_validate` に失敗した文書は `logging.warning` に ID と誤りの数を出して飛ばし、残りを処理する。グラフは `store.query("artifacts")` から、見張りは `store.query("watches")` から作る（1回の呼び出しで1度だけ読む）。

- `handle_test_runs`: 同じ機能の試験結果を `store.query("test_runs", {"feature": run.feature})` で読み、`route_test_run` に渡す
- `mail_request`: `id=idempotency_key(to_team, "mail", [mail.id])`、`trigger="mail"`、`origin_artifact_id=related_artifact_ids[0]`（なければ `None`）、`source_ids=[mail.id]`、`impact=None`、`matched_watch_ids=[]`、`floor` は決定6、`not_before=mail.created_at`

- [ ] **Step 1: 失敗するテストを書く**

```python
@pytest.fixture
def store():
    s = MemoryStore()
    ds = build_dataset()
    for a in ds.artifacts:
        s.create("artifacts", a.model_dump(mode="json") | {"origin": "seed"})
    for r in ds.test_runs:
        s.create("test_runs", r.model_dump(mode="json") | {"origin": "seed"})
    return s

S1 = SCENARIOS["s1_signal_period"].steps[0].change.model_dump(mode="json")

def test_signal_change_enqueues_owner_team(store):
    [rid] = handle_change_events([S1], store)
    rec = store.get("investigations", rid)
    assert rec["team"] == "integrated_control" and rec["floor"] == "notify_now"
    assert len(rec["impact"]["impacted_ids"]) == 8

def test_same_batch_twice_makes_one_request(store):          # Review Focus 1
    handle_change_events([S1], store)
    assert handle_change_events([S1], store) == []
    assert len(store.query("investigations")) == 1

def test_seed_docs_are_ignored(store):                        # Review Focus 2
    seeded = [r.model_dump(mode="json") | {"origin": "seed"} for r in build_dataset().test_runs]
    assert handle_test_runs(seeded, store) == []
    assert handle_change_events([S1 | {"origin": "seed"}], store) == []

def test_broken_doc_is_skipped_and_rest_processed(store):     # Review Focus 5
    broken = {"id": "ce-bad", "vehicle_id": "kakuu-suv", "artifact_id": "SIG-BrkPedalPos"}
    assert len(handle_change_events([broken, S1], store)) == 1

def test_third_hils_failure_with_watch_enqueues(store):
    store.create("watches", Watch(id="w1", team="integrated_control", kind="test_failure_streak",
        description="回生協調の HILS", feature="regen_coord", streak=3, delivery="immediate",
        created_by="tanaka", created_at=SEED_NOW).model_dump(mode="json"))
    steps = SCENARIOS["s2_hils_streak"].steps
    ids = []
    for st in steps:
        doc = st.test_run.model_dump(mode="json")
        store.create("test_runs", doc)
        ids += handle_test_runs([doc], store)
    last = store.get("investigations", ids[-1])
    assert last["floor"] == "notify_now" and last["matched_watch_ids"] == ["w1"]

def test_impact_notice_mail_wakes_recipient_with_notify_now(store):
    mail = AgentMail(id="am-1", thread_id="th-1", from_team="integrated_control", to_team="motor_control",
                     kind="impact_notice", body="MDL-MotorTq に影響", related_artifact_ids=["SIG-BrkPedalPos"],
                     created_at=datetime(2026, 11, 18, 8, 5, tzinfo=JST))
    [rid] = handle_agent_mail([mail.model_dump(mode="json")], store)
    rec = store.get("investigations", rid)
    assert rec["team"] == "motor_control" and rec["trigger"] == "mail" and rec["floor"] == "notify_now"

def test_analysis_request_mail_is_silent_floor(store):
    mail = AgentMail(id="am-2", thread_id="th-1", from_team="integrated_control", to_team="evaluation",
                     kind="analysis_request", body="応答の遅れを見て", created_at=datetime(2026, 11, 17, 21, 20, tzinfo=JST))
    [rid] = handle_agent_mail([mail.model_dump(mode="json")], store)
    assert store.get("investigations", rid)["floor"] == "silent"
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_handlers.py -v` / Expected: FAIL
- [ ] **Step 3: 実装する**
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -v` / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): 変更・試験結果・メールの変更フィードから調査依頼を作る処理を追加"`

---

### Task 6: tick（配達、定時の仕事、返事の期限切れ、受け渡し）

**Files:**
- Create: `functions/proactive_functions/tick.py`
- Modify: `functions/tests/fakes.py`（`RecordingPublisher`）
- Test: `functions/tests/test_tick.py`

**Interfaces:**
- Consumes: `Notification`、`Schedule`、`AgentMail`、`needs_escalation`、`idempotency_key`、`enqueue`、`dispatch_due`、`Publisher`（Task 8 で本物を作る。ここではプロトコルだけ `publisher.py` に置く: `class Publisher(Protocol): def publish(self, team: Team, event: dict) -> None`）
- Produces:
  - `class TickReport(BaseModel)`: `delivered_notification_ids: list[str]`、`ran_schedule_ids: list[str]`、`overdue_thread_ids: list[str]`、`dispatched_ids: list[str]`
  - `def run_tick(store: Store, invoker: AgentInvoker, publisher: Publisher, now: datetime) -> TickReport`

`run_tick` の順番（朝の個別の知らせを、朝のまとめより先に届けるため、この順を守る）:
1. **配達**: `delivered_at` が空で、`deliver_at` があり `<= now` の通知に `delivered_at=now` を etag 付きで書き、`publisher.publish(team, {"type": "refresh", "kind": "notifications", "id": id, "team": team})`
2. **定時の仕事**: `done_at` が空で `due_at <= now` の予定ごとに、依頼 `id=idempotency_key(team, "schedule", [schedule.id])`、`trigger="schedule"`、`origin_artifact_id=None`、`source_ids=[schedule.id]`、`impact=None`、`floor="silent"`、`not_before=due_at` を `enqueue`。予定に `done_at=now` を etag 付きで書く。`payload.recur == "daily"` なら次の回を新規作成する（ID は `f"{series}-{次の日付:%Y%m%d}"`、時刻は決定13、`Conflict` は飛ばす）
3. **返事の期限切れ**: `kind == "impact_notice"` のメールのスレッドごとに `needs_escalation(スレッドの全メール, now)`。`reason == "no_reply"` なら、依頼 `team=<最初の impact_notice の from_team>`、`trigger="mail"`、`source_ids=[f"overdue:{thread_id}"]`、`id=idempotency_key(team, "mail", source_ids)`、`floor="silent"`、`not_before=now` を `enqueue`
4. **受け渡し**: `dispatch_due(store, invoker, now)`

- [ ] **Step 1: 失敗するテストを書く**

```python
NIGHT = datetime(2026, 11, 17, 21, 10, tzinfo=JST)
MORNING = datetime(2026, 11, 18, 8, 0, tzinfo=JST)

def notif(id_, deliver_at, delivered_at=None):
    return Notification(id=id_, team="integrated_control", origin_artifact_id="SIG-BrkPedalPos", impacted_ids=[],
                        highlight_ids=[], cross_team_edges=[], classification="notify_now", deliver_at=deliver_at,
                        delivered_at=delivered_at, reason="r", created_at=NIGHT).model_dump(mode="json")

def tick(store, now, pub=None, inv=None):
    return run_tick(store, inv or RecordingInvoker(), pub or RecordingPublisher(), now)

def test_deferred_notification_delivered_once_at_morning():
    store, pub = MemoryStore(), RecordingPublisher()
    store.create("notifications", notif("n1", MORNING))
    assert tick(store, NIGHT, pub).delivered_notification_ids == []
    assert tick(store, MORNING, pub).delivered_notification_ids == ["n1"]
    assert tick(store, MORNING + timedelta(minutes=1), pub).delivered_notification_ids == []
    assert pub.events == [("integrated_control", {"type": "refresh", "kind": "notifications", "id": "n1", "team": "integrated_control"})]

def test_daily_schedule_runs_and_creates_next():
    store = MemoryStore()
    for s in build_schedules(build_dataset()):
        store.create("schedules", s.model_dump(mode="json"))
    rep = tick(store, MORNING)
    assert "sch-digest-integrated_control-20261118" in rep.ran_schedule_ids
    assert store.get("schedules", "sch-digest-integrated_control-20261119")["due_at"].startswith("2026-11-19T08:00")
    assert "sch-release-gap-R3" not in rep.ran_schedule_ids

def test_jump_several_days_runs_daily_once_and_next_is_future():   # Review Focus 3
    store = MemoryStore()
    for s in build_schedules(build_dataset()):
        store.create("schedules", s.model_dump(mode="json"))
    jump = datetime(2026, 11, 23, 8, 0, tzinfo=JST)
    rep = tick(store, jump)
    digests = [i for i in rep.ran_schedule_ids if i.startswith("sch-digest-integrated_control")]
    assert digests == ["sch-digest-integrated_control-20261118"]
    assert "sch-release-gap-R3" in rep.ran_schedule_ids
    nxt = [s for s in store.query("schedules", {"done_at": None}) if s["id"].startswith("sch-digest-integrated_control")]
    assert [s["id"] for s in nxt] == ["sch-digest-integrated_control-20261124"]

def test_overdue_reply_wakes_sender_once():
    store = MemoryStore()
    sent = datetime(2026, 11, 18, 8, 10, tzinfo=JST)
    store.create("agent_mail", AgentMail(id="am-1", thread_id="th-1", from_team="integrated_control",
        to_team="motor_control", kind="impact_notice", body="x", created_at=sent).model_dump(mode="json"))
    assert tick(store, sent + timedelta(hours=47)).overdue_thread_ids == []
    rep = tick(store, sent + timedelta(hours=48))
    assert rep.overdue_thread_ids == ["th-1"]
    recs = store.query("investigations", {"trigger": "mail"})
    assert [r["team"] for r in recs] == ["integrated_control"]
    tick(store, sent + timedelta(hours=49))
    assert len(store.query("investigations", {"trigger": "mail"})) == 1

def test_tick_with_earlier_clock_changes_nothing():
    store = MemoryStore()
    store.create("notifications", notif("n1", MORNING, delivered_at=MORNING))
    rep = tick(store, NIGHT)
    assert rep == TickReport(delivered_notification_ids=[], ran_schedule_ids=[], overdue_thread_ids=[], dispatched_ids=[])
    assert store.get("notifications", "n1")["delivered_at"] is not None
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_tick.py -v` / Expected: FAIL
- [ ] **Step 3: 実装する**
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -v` / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): tick（配達、定時の仕事、返事の期限切れ、受け渡し）を追加"`

---

### Task 7: トークンの検証と書き込み窓口の HTTP 処理

**Files:**
- Create: `functions/proactive_functions/auth.py`、`functions/proactive_functions/gateway_http.py`
- Modify: `functions/tests/fakes.py`（`FakeVerifier`）
- Test: `functions/tests/test_auth.py`、`functions/tests/test_gateway_http.py`

**Interfaces:**
- Consumes: `authorize_agent_write`、`WriteDenied`、`decide_delivery`、`analyze_impact`、`Graph`、`Notification`、`TeamSettings`、`Message`、`AgentMail`
- Produces（`auth.py`）:
  - `class AuthError(Exception)`（属性 `reason: str`）
  - `class TokenVerifier(Protocol): def verify(self, authorization: str | None) -> str`（呼び出し元の client ID を返す）
  - `class EntraTokenVerifier`: `__init__(tenant_id: str, audiences: list[str], jwks_client: PyJWKClient | None = None)`。`jwks_client` が `None` なら `https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys` を使う。`Bearer ` で始まらない、署名が合わない、期限切れ、`aud` が `audiences` にない、`iss` が `https://login.microsoftonline.com/{tenant_id}/v2.0` と `https://sts.windows.net/{tenant_id}/` のどちらでもない、`tid` が違う、`azp` も `appid` もない → `AuthError`。アルゴリズムは `RS256` だけ
- Produces（`gateway_http.py`）:
  - `class HttpResult(BaseModel)`: `status: int`、`body: dict | None`
  - `def team_for_client(store: Store, client_id: str) -> str | None`（`team_settings` の `agent_client_id` が一致するチーム）
  - `def handle_agent_write(method: str, container: str, item_id: str | None, authorization: str | None, body: bytes, *, store: Store, verifier: TokenVerifier, now: datetime) -> HttpResult`

`handle_agent_write` の応答:
| 場面 | 応答 |
|---|---|
| `AuthError` | `401 {"reason": ...}` |
| `POST`（`item_id` なし）。JSON が読めない | `400` |
| `POST`。`authorize_agent_write(team_for_client(...), container, doc, lookup_message, lookup_thread=..., now=now)` が `WriteDenied` | `403 {"reason": ...}` |
| `POST`。通知なら決定8で `deliver_at` と `delivered_at` を決めてから、`store.create(container, model.model_dump(mode="json"))`。`Conflict` | `409 {"reason": "同じ ID の文書が既にあります"}` |
| `POST` 成功 | `201`（保存した文書） |
| `PUT agent_runs/{id}`: 既存がない `404`、既存の `team` が呼び出し元と違う `403`、本文の `id` が `item_id` と違う `400`、検査は `authorize_agent_write`、`store.replace(..., etag=既存の _etag)`。`Conflict` は `409`。成功 | `200` |
| `DELETE watches/{id}`: 呼び出し元のチームがわからない `403`、既存がない `404`、既存の `team` が違う `403`。成功 | `204` |
| 上記以外のメソッドとコンテナーの組み合わせ | `405` |

`lookup_message` は `store.get("messages", id)` を `Message` にしたもの、`lookup_thread` は `store.query("agent_mail", {"thread_id": thread_id})` を `AgentMail` にしたもの。

- [ ] **Step 1: 失敗するテストを書く**

```python
# functions/tests/test_auth.py  — テスト用の RSA 鍵でトークンを作り、偽の JWKS で検証する
TENANT = "11111111-1111-1111-1111-111111111111"
AUD = "22222222-2222-2222-2222-222222222222"

def token(key, **claims):
    base = {"aud": AUD, "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "tid": TENANT,
            "azp": "agent-ic", "exp": int(time.time()) + 600}
    return "Bearer " + jwt.encode(base | claims, key, algorithm="RS256")

def test_valid_token_returns_client_id(verifier, key):
    assert verifier.verify(token(key)) == "agent-ic"

def test_v1_token_uses_appid(verifier, key):
    t = token(key, iss=f"https://sts.windows.net/{TENANT}/", azp=None, appid="agent-ev")
    assert verifier.verify(t) == "agent-ev"

@pytest.mark.parametrize("claims", [{"aud": "someone-else"}, {"iss": "https://evil/"}, {"tid": "x"},
                                    {"exp": int(time.time()) - 10}, {"azp": None}])
def test_bad_claims_rejected(verifier, key, claims):
    with pytest.raises(AuthError):
        verifier.verify(token(key, **claims))

@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer not-a-jwt"])
def test_malformed_header_rejected(verifier, header):
    with pytest.raises(AuthError):
        verifier.verify(header)

def test_token_signed_by_other_key_rejected(verifier, other_key):
    with pytest.raises(AuthError):
        verifier.verify(token(other_key))

# functions/tests/test_gateway_http.py — FakeVerifier は "Bearer <client_id>" をそのまま返す
NOW = datetime(2026, 11, 17, 21, 20, tzinfo=JST)

@pytest.fixture
def store():
    s = MemoryStore()
    ds = build_dataset()
    for a in ds.artifacts:
        s.create("artifacts", a.model_dump(mode="json"))
    for ts in ds.team_settings:
        cid = {"integrated_control": "agent-ic", "motor_control": "agent-mc"}.get(ts.team.value)
        s.create("team_settings", ts.model_copy(update={"agent_client_id": cid}).model_dump(mode="json"))
    return s

def call(store, method, container, body=None, item_id=None, client="agent-ic"):
    raw = json.dumps(body).encode() if body is not None else b""
    return handle_agent_write(method, container, item_id, f"Bearer {client}" if client else None, raw,
                              store=store, verifier=FakeVerifier(), now=NOW)

def msg(**kw):
    return dict(id="m1", vehicle_id="kakuu-suv", team="integrated_control", role="assistant", author="agent",
                text="x", created_at="2026-11-17T00:00:00+09:00") | kw

def test_no_token_is_401(store):
    assert call(store, "POST", "messages", msg(), client=None).status == 401

def test_unknown_client_is_403(store):                       # 正しい aud でも対応表にないアプリは拒否
    assert call(store, "POST", "messages", msg(), client="some-other-app").status == 403

def test_own_message_created_with_gateway_time(store):
    r = call(store, "POST", "messages", msg())
    assert r.status == 201 and r.body["created_at"].startswith("2026-11-17T21:20")

def test_existing_id_is_409_and_not_overwritten(store):
    call(store, "POST", "messages", msg(text="最初"))
    assert call(store, "POST", "messages", msg(text="上書き")).status == 409
    assert store.get("messages", "m1")["text"] == "最初"

def test_impact_notice_by_agent_is_403(store):
    mail = dict(id="am1", vehicle_id="kakuu-suv", thread_id="t", from_team="integrated_control",
                to_team="motor_control", kind="impact_notice", body="x", created_at="2026-11-17T21:20:00+09:00")
    assert call(store, "POST", "agent_mail", mail).status == 403

def test_night_notification_is_deferred_to_morning(store):
    n = dict(id="n1", vehicle_id="kakuu-suv", team="integrated_control", origin_artifact_id="SIG-BrkPedalPos",
             impacted_ids=[], highlight_ids=[], cross_team_edges=[], classification="notify_now",
             deliver_at="2026-11-17T21:20:00+09:00", reason="R3 に響く", created_at="2026-11-17T21:20:00+09:00")
    r = call(store, "POST", "notifications", n)
    assert r.status == 201
    assert r.body["deliver_at"].startswith("2026-11-18T08:00") and r.body["delivered_at"] is None

def test_agent_run_update_only_own_team(store):
    run = dict(id="run1", vehicle_id="kakuu-suv", team="integrated_control", state="running", title="影響の調査",
               started_at="2026-11-17T21:20:00+09:00")
    call(store, "POST", "agent_runs", run)
    assert call(store, "PUT", "agent_runs", run | {"state": "done"}, item_id="run1").status == 200
    assert call(store, "PUT", "agent_runs", run | {"state": "done"}, item_id="run1", client="agent-mc").status == 403

def test_watch_delete_only_own_team(store):
    w = dict(id="w1", vehicle_id="kakuu-suv", team="integrated_control", kind="test_failure_streak",
             description="d", feature="regen_coord", delivery="immediate", created_by="tanaka",
             created_at="2026-11-17T21:20:00+09:00")
    call(store, "POST", "watches", w)
    assert call(store, "DELETE", "watches", item_id="w1", client="agent-mc").status == 403
    assert call(store, "DELETE", "watches", item_id="w1").status == 204
    assert store.get("watches", "w1") is None

def test_put_on_messages_is_405(store):
    assert call(store, "PUT", "messages", msg(), item_id="m1").status == 405
```
（`verifier`、`key`、`other_key` の fixture は `cryptography` で RSA 鍵を作り、`get_signing_key_from_jwt(token)` が `key.public_key()` を `.key` に持つ偽の JWKS クライアントを返す。`conftest.py` に置く）

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_auth.py tests/test_gateway_http.py -v` / Expected: FAIL
- [ ] **Step 3: 実装する**
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -v` / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): Entra トークンの検証と書き込み窓口の HTTP 処理を追加"`

---

### Task 8: 画面への通知（Web PubSub）

**Files:**
- Modify: `functions/proactive_functions/publisher.py`
- Test: `functions/tests/test_publisher.py`

**Interfaces:**
- Produces:
  - `class WebPubSubPublisher(Publisher)`: `__init__(endpoint: str, hub: str, credential)`。`WebPubSubServiceClient(endpoint=..., hub=..., credential=...)` の `send_to_group(group=team.value, message=event, content_type="application/json")`
  - `PUBLISHED_CONTAINERS = ("messages", "proposals", "agent_runs", "notifications", "watches")`
  - `def publish_changes(container: str, docs: list[dict], store: Store, publisher: Publisher) -> int`（送った合図の数を返す）

`publish_changes` の規則（決定9）: `origin == "seed"` は送らない。`notifications` は `delivered_at` が空なら送らない。`messages` は `notification_id` があり、その通知の `delivered_at` が空なら送らない。`team` がない文書は送らない。合図は `{"type": "refresh", "kind": container, "id": doc["id"], "team": doc["team"]}`。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_message_publishes_refresh():
    store, pub = MemoryStore(), RecordingPublisher()
    doc = {"id": "m1", "vehicle_id": "kakuu-suv", "team": "integrated_control", "notification_id": None}
    assert publish_changes("messages", [doc], store, pub) == 1
    assert pub.events == [("integrated_control", {"type": "refresh", "kind": "messages", "id": "m1", "team": "integrated_control"})]

def test_message_of_undelivered_notification_is_held():
    store, pub = MemoryStore(), RecordingPublisher()
    store.create("notifications", {"id": "n1", "vehicle_id": "kakuu-suv", "team": "integrated_control", "delivered_at": None})
    doc = {"id": "m1", "vehicle_id": "kakuu-suv", "team": "integrated_control", "notification_id": "n1"}
    assert publish_changes("messages", [doc], store, pub) == 0

def test_undelivered_notification_is_held_and_delivered_one_is_sent():
    store, pub = MemoryStore(), RecordingPublisher()
    held = {"id": "n1", "vehicle_id": "kakuu-suv", "team": "integrated_control", "delivered_at": None}
    sent = {"id": "n2", "vehicle_id": "kakuu-suv", "team": "integrated_control", "delivered_at": "2026-11-18T08:00:00+09:00"}
    assert publish_changes("notifications", [held, sent], store, pub) == 1

def test_seed_docs_are_not_published():
    store, pub = MemoryStore(), RecordingPublisher()
    doc = {"id": "w1", "vehicle_id": "kakuu-suv", "team": "integrated_control", "origin": "seed"}
    assert publish_changes("watches", [doc], store, pub) == 0

def test_webpubsub_publisher_sends_to_team_group(monkeypatch):
    sent = []
    class FakeClient:
        def __init__(self, **kw): pass
        def send_to_group(self, group, message, content_type): sent.append((group, message, content_type))
    monkeypatch.setattr("proactive_functions.publisher.WebPubSubServiceClient", FakeClient)
    WebPubSubPublisher("https://x.webpubsub.azure.com", "proactive", object()).publish(Team.EVALUATION, {"type": "refresh"})
    assert sent == [("evaluation", {"type": "refresh"}, "application/json")]
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_publisher.py -v` / Expected: FAIL
- [ ] **Step 3: 実装する**
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -v` / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): Web PubSub で画面に再読み込みの合図を送る処理を追加"`

---

### Task 9: シード投入、時計の操作、トリガーの配線

**Files:**
- Create: `functions/proactive_functions/seeding.py`、`functions/proactive_functions/settings.py`、`scripts/seed.py`、`scripts/clock.py`
- Modify: `functions/function_app.py`、`azure.yaml`（`postprovision` フックを足す）
- Test: `functions/tests/test_seeding.py`、`functions/tests/test_function_app.py`

**Interfaces:**
- Produces（`seeding.py`）:
  - `DATA_CONTAINERS: tuple[str, ...]`（`leases` 以外の 13 コンテナー）
  - `def seed_store(store: Store, *, reset: bool, system_now: datetime) -> dict[str, int]`（コンテナーごとに作った件数）
    - `reset=True`: 既存の `team_settings` から `agent_client_id` を控え、`DATA_CONTAINERS` の文書をすべて消し、作り直して控えを戻し、時計を `SEED_NOW` に合わせる
    - `reset=False`: 足りない文書だけを新規作成する。時計の文書がなければ `SEED_NOW` に合わせる。あれば触らない
    - 書くもの: `build_dataset()` の `artifacts`、`test_runs`、`team_settings`、`build_schedules()` の `schedules`。すべてに `"origin": "seed"` を付ける
- Produces（`settings.py`）: `class Settings(BaseModel)`: `cosmos_endpoint`、`cosmos_database`、`webpubsub_endpoint`、`webpubsub_hub`、`gateway_tenant_id`、`gateway_audiences: list[str]`、`agent_invoker: Literal["log"]`。`def load_settings(env: Mapping[str, str] = os.environ) -> Settings`
- Produces（`function_app.py`）: 依存（Store、Clock、Invoker、Publisher、Verifier）は最初の呼び出しで1度だけ作る（import しただけでは Azure に触れない）。登録する関数:

| 関数名 | トリガー | 呼ぶもの |
|---|---|---|
| `health` | HTTP GET `health` | （Task 2） |
| `agent_write` | HTTP POST/PUT/DELETE `agent/{container}/{item_id?}`、匿名 | `handle_agent_write(..., now=clock.now())` |
| `route_change_events` | Cosmos `change_events`、リースの接頭辞 `route-ce-` | `handle_change_events` |
| `route_test_runs` | Cosmos `test_runs`、`route-tr-` | `handle_test_runs` |
| `deliver_agent_mail` | Cosmos `agent_mail`、`mail-` | `handle_agent_mail` |
| `tick_on_clock` | Cosmos `system`、`tick-` | `run_tick(..., now=clock.now())` |
| `tick_timer` | タイマー `0 */1 * * * *` | `run_tick(..., now=clock.now())` |
| `publish_<コンテナー>` ×5 | Cosmos の各 `PUBLISHED_CONTAINERS`、`pub-<コンテナー>-` | `publish_changes` |

  Cosmos トリガーは `connection="COSMOS"`、`database_name="%COSMOS_DATABASE%"`、`lease_container_name="leases"`、`create_lease_container_if_not_exists=False`。文書は `json.loads(d.to_json())` で dict にする。
- Produces（`scripts/seed.py`）: `uv run --package proactive-functions python scripts/seed.py [--reset]`。環境変数 `COSMOS_ENDPOINT`（azd のフックでは azd の環境の値が渡る。手で動かすときは `azd env get-values` の値を読む）。結果の件数を表示する。`--reset` は「Azure 上のデータを消す操作」なので、手で動かす前に制作者に確認する
- Produces（`scripts/clock.py`）: `show`（仮想時刻とずれを表示）、`set <ISO 8601 のタイムゾーン付き日時>`（`set_virtual_now`）

- [ ] **Step 1: 失敗するテストを書く**

```python
# functions/tests/test_seeding.py
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=JST)

def test_seed_into_empty_store():
    store = MemoryStore()
    counts = seed_store(store, reset=False, system_now=NOW)
    assert counts["artifacts"] == 43 and counts["test_runs"] == 26 and counts["team_settings"] == 7 and counts["schedules"] == 5
    assert all(d["origin"] == "seed" for d in store.query("test_runs"))
    assert StoredClock(store, VirtualClock(NOW)).now() == SEED_NOW

def test_seed_without_reset_keeps_existing_and_clock():
    store = MemoryStore()
    seed_store(store, reset=False, system_now=NOW)
    set_virtual_now(store, datetime(2026, 11, 20, 9, 0, tzinfo=JST), NOW)
    store.create("messages", {"id": "m1", "vehicle_id": "kakuu-suv", "team": "integrated_control"})
    counts = seed_store(store, reset=False, system_now=NOW)
    assert counts["artifacts"] == 0
    assert store.get("messages", "m1") is not None
    assert StoredClock(store, VirtualClock(NOW)).now() == datetime(2026, 11, 20, 9, 0, tzinfo=JST)

def test_reset_clears_and_keeps_agent_client_id():
    store = MemoryStore()
    seed_store(store, reset=False, system_now=NOW)
    ts = store.get("team_settings", "ts-integrated_control")
    store.replace("team_settings", ts | {"agent_client_id": "agent-ic"}, etag=ts["_etag"])
    store.create("messages", {"id": "m1", "vehicle_id": "kakuu-suv", "team": "integrated_control"})
    seed_store(store, reset=True, system_now=NOW)
    assert store.get("messages", "m1") is None
    assert store.get("team_settings", "ts-integrated_control")["agent_client_id"] == "agent-ic"
    assert StoredClock(store, VirtualClock(NOW)).now() == SEED_NOW

# functions/tests/test_function_app.py に追加
def test_all_functions_registered_without_touching_azure(monkeypatch):
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)       # import だけでは設定を読まない
    import importlib, function_app
    importlib.reload(function_app)
    names = {f.get_function_name() for f in function_app.app.get_functions()}
    assert names == {"health", "agent_write", "route_change_events", "route_test_runs", "deliver_agent_mail",
                     "tick_on_clock", "tick_timer", "publish_messages", "publish_proposals", "publish_agent_runs",
                     "publish_notifications", "publish_watches"}

def test_load_settings_reads_audiences_list():
    s = load_settings({"COSMOS_ENDPOINT": "https://c", "COSMOS_DATABASE": "proactive", "WEBPUBSUB_ENDPOINT": "https://w",
                       "WEBPUBSUB_HUB": "proactive", "GATEWAY_TENANT_ID": "t", "GATEWAY_AUDIENCES": "a,api://t/b",
                       "AGENT_INVOKER": "log"})
    assert s.gateway_audiences == ["a", "api://t/b"]
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_seeding.py tests/test_function_app.py -v` / Expected: FAIL
- [ ] **Step 3: 実装する** — `azure.yaml` に `postprovision` フック（Task 2 の例のとおり）を足す
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -v && uv run --directory core pytest -q` / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): シード投入、仮想時計の操作、すべてのトリガーの配線を追加"`

---

### Task 10: Azure 上での通し確認（スモークテスト）と README

**Files:**
- Create: `scripts/smoke.py`
- Modify: `README.md`、`docs/superpowers/plans/2026-11-08-plan2-infra-functions.md`（末尾に「実装時の決定」を追記）

**Interfaces:**
- Produces（`scripts/smoke.py`）: `uv run --package proactive-functions python scripts/smoke.py`。azd の環境の値を読み、次を順に確かめて、各項目の合否と最後に `SMOKE OK` か `SMOKE FAILED` を表示する（失敗なら終了コード 1）:
  1. `seed_store(reset=True)` でデータを作り直す
  2. 時計を 2026-11-17 21:10 JST に合わせ、s1 の変更イベント `ce-s1-1` を `change_events` に書く
  3. 時計を 21:14 に合わせる（まとめの窓を越える）。90 秒以内に `investigations` の `idempotency_key(integrated_control, "change", ["ce-s1-1"])` が `dispatched` になる
  4. 同じ変更イベントを `upsert` でもう一度書く（変更フィードに再び流れる）。60 秒待っても、`source_ids` に `ce-s1-1` を含む記録は1件のまま（設計書 9 章「二重通知がないこと」）
  5. トークンなしの `POST {FUNCTION_APP_URL}/api/agent/messages` が 401。`az account get-access-token` で取った管理用のトークン（`aud` が違う）でも 401
  6. 最後に `seed_store(reset=True)` で元に戻す

- [ ] **Step 1: スモークテストを書く**（Azure 上で動かす確認なので、単体テストの RED-GREEN はない。`smoke.py` の中の待ち合わせは、1秒ごとに読み直して上限時間で打ち切る）
- [ ] **Step 2: 【制作者に確認してから】デプロイしてスモークテストを流す** — 制作者に「`azd up` で Functions を更新し、Azure 上のデモ用データをリセットしてスモークテストを流します。進めてよいですか」と確認する。了承を得たら:
  Run: `azd up`、続けて `uv run --package proactive-functions python scripts/smoke.py`
  Expected: `SMOKE OK`。失敗したら、Application Insights のログ（`traces` の `route_change_events`、`tick_on_clock`）で原因を突き止めてから直す
- [ ] **Step 3: Cosmos の契約テストを本物でも流す** — Run: `COSMOS_TEST_ENDPOINT="$(azd env get-value COSMOS_ENDPOINT)" uv run --directory functions pytest tests/test_store_contract.py -v` / Expected: `memory` と `cosmos` の両方が PASS
- [ ] **Step 4: README を更新する** — 次の節を足す（日本語。yomiyasu の書き方に沿う）:
  - 「Azure へのデプロイ」: 前提（Azure CLI、azd 1.37 以降、uv、Azure Functions Core Tools は任意。Entra でアプリ登録を作れる権限）、`azd auth login`、`azd env new <名前> --location japaneast`、`azd up`、`azd down --purge`
  - 「地域」: japaneast を選んだ理由（Global Constraints の 5 サービスがそろう、2026-11-08 時点）
  - 「費用」: 使わないときにほぼゼロになる理由（サーバーレスと Flex Consumption、Web PubSub Free）。1分ごとのタイマーが動き続けるが、Flex Consumption の無料枠に収まる見込みであること
  - 「デモのデータと時計」: `scripts/seed.py [--reset]`、`scripts/clock.py show|set`
  - 「状態」を「Plan 2 まで実装済み」に直す
- [ ] **Step 5: 計画書の末尾に「実装時の決定」を書く**（Plan 1 と同じ形式。下の「Plan 3 と Plan 4 への申し送り」を、実装で変わった点に合わせて直す）
- [ ] **Step 6: Commit** — `git commit -m "docs: Plan 2 のデプロイ手順、地域、費用を README に追記し、スモークテストを追加"`

---

## Plan 3 と Plan 4 への申し送り

- **エージェントの ID と窓口**（Plan 3）: エージェントを作ったら、各チームの `team_settings.agent_client_id` にエージェント ID の client ID を入れる（Functions の再デプロイは不要）。エージェントのコードは `DefaultAzureCredential().get_token(f"{GATEWAY_APP_ID_URI}/.default")` でトークンを取り、`{FUNCTION_APP_URL}/api/agent/{container}` を呼ぶ
- **エージェントの読み取り権限**（Plan 3）: エージェント ID の object ID に、Cosmos の組み込み Data Reader（`00000000-0000-0000-0000-000000000001`）を `sqlRoleAssignments` で付ける。書き込み権限は付けない（設計書 7.5 節）
- **本物の受け渡し**（Plan 3）: `AgentInvoker` を実装したクラスを足し、`AGENT_INVOKER` の値で切り替える。`invoke` は時間のかかる処理を待たない（バックグラウンド実行を始めたら戻る）
- **変更イベントを書く側**（Plan 4）: シナリオ再生は `change_events` に書くと同時に、`artifacts` の該当データも変更後の値に更新する（Functions は `artifacts` を書き換えない）。仮想時計は `system/clock` の `offset_seconds` を書けば、Functions の tick が動く
- **画面への通知**（Plan 4）: Web PubSub のグループ名はチームの値。合図は `{"type": "refresh", "kind", "id", "team"}` だけなので、画面は合図を受けたら BFF から読み直す。配達前の通知とそれにひもづくメッセージは、BFF も画面に出さない（`delivered_at` が空なら出さない）
- **人の承認の実行**（Plan 4）: BFF は `impact_notice` を `agent_mail` に書き、`proposals` の `status`・`decided_by`・`decided_at` を更新する。BFF の ID には Cosmos の Data Contributor を付ける

---

## 実装時の決定（実装後に追記）

実装中と最終レビューで決めたこと。Plan 3 と Plan 4 はこれを前提にする。

- Functions のマネージド ID は `infra/modules/identity.bicep` に分けた（Cosmos と Web PubSub の権限を、Functions のモジュールより先に付けるため）
- 初回の `azd up` は、プロビジョニングと並行して始まる発行がタグ付きのリソースを見つけられずに失敗することがある。`azd deploy` だけをやり直せば通る（README に記載）
- `scripts/_azd.py` に、azd の環境の値の読み取りと `CosmosStore` の用意をまとめた（seed、clock、smoke の3つで使う）
- tick の `overdue_thread_ids` には、その回に新しく起こしたスレッドだけを入れる
- `notification_id` が存在しない通知を指すメッセージは、画面への合図を送らない（届けていない通知とみなす）
- `uv sync --all-packages` のあとで `proactive_functions` が import できないときは、`uv sync --all-packages --reinstall-package proactive-functions` で直る（パッケージのディレクトリが空のうちに同期したため）
- **最終レビューで直したこと**:
  - Review Focus 5 の前提が逆だった。Cosmos のトリガーは例外の出たバッチを「永久に再試行」するのではなく、既定では再試行せずに読み飛ばす（そのバッチは失われる）。Cosmos のトリガー 9 個すべてに再試行の設定（指数バックオフ、最大 5 回、5 秒〜5 分）を付けた。処理はどれも冪等なので安全
  - 保存済みの壊れた文書（artifacts、watches、試験結果の履歴、通知、予定、メール、調査依頼）が1件あると、振り分けや tick が止まっていた。1件ずつ検証して、壊れたものだけ飛ばす（`proactive_functions/docs.py`）。チーム名が壊れた文書は画面に合図を送らない
  - 複数をまとめた調査依頼は、まとめた記録の新規作成を「確保」とする。元の記録の印付けは後から行う（途中で止まったり、二つの tick が別の順で確保したりしても、依頼を失わない）
  - 定時の仕事は、実行済みの印を付ける前に、依頼と次の回を作る（途中で止まっても毎日の予定が途切れない）
- **Plan 3 への申し送り（追加）**: 書き込み窓口のサービスプリンシパルに `appRoleAssignmentRequired: true` を付け、エージェント ID にだけアプリロールを割り当てると、窓口宛てのトークンを取れるアプリを絞れる（client ID の対応表に加える多層の防御）
- 2026-11-08 に `proactive-dev`（japaneast）へデプロイし、`scripts/smoke.py` と、本物の Cosmos での Store の契約テストが通った
