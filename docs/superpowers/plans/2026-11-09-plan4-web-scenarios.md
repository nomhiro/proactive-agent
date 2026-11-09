# Plan 4: Web アプリ（BFF と画面）、シナリオの再生、シナリオテスト Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `azd up` で Container Apps に Web アプリができ、Entra でサインインした人が「田中 / 佐藤 / 鈴木 / 高橋」として、会話・影響マップ・見張りと設定の3区画を見て、チャットし、承認できる。シナリオを画面のボタンか CLI で1手ずつ進められ、5つのシナリオを本物の LLM で通すシナリオテストがある。

**Architecture:** 新しいワークスペースのメンバー `web/`（`proactive_web`）に FastAPI の BFF を置き、Plan 2〜3 の `CosmosStore`、`StoredClock`、`seed_store` をそのまま使う。画面は `web/frontend/`（React + Vite + TypeScript）で作り、ビルドしたファイルを BFF が配る。1つのコンテナにまとめ、Container Apps の組み込み認証（Entra）で守る。チャットはチームに1本の会話へ BFF の ID で送り、返事は画面の再読み込みのときに BFF が受け取って `messages` に書き写す（裏で待ち続ける処理を持たない）。

**Tech Stack:** Python 3.12、FastAPI、uvicorn、azure-ai-projects 2.10 以降、azure-identity、azure-messaging-webpubsubservice、azure-cosmos、React 18.3.1、Vite 5.4、TypeScript 5.6、Vitest 2.1、Bicep（Microsoft Graph 拡張）、azd（`host: containerapp`、リモートビルド）、pytest

**Spec:** `docs/superpowers/specs/2026-11-07-proactive-vehicle-agent-design.md` 第2版（特に 4.2、5、6、7.2、7.4、7.5、7.7〜7.9、9 節）。前提: Plan 2 と Plan 3 の末尾「実装時の決定」「Plan 4 への申し送り」

### 計画全体の中での位置づけ
| 計画 | 中身 |
|---|---|
| Plan 1（済） | `vehicle_core`: 判定ロジックと架空データ |
| Plan 2（済） | azd + Bicep の基盤、Functions（振り分け、まとめ、定時実行、メール配達、画面への通知） |
| Plan 3（済） | MCP サーバー、本物の `AgentInvoker`、エージェント4体、Routines、デプロイのフック |
| **Plan 4（本書）** | Web アプリ（BFF と画面、チャット、承認、グラフの表示）、シナリオを進める仕組み、シナリオテスト |

### 始める前に
- ブランチ: `main` から `feat/plan4-web-scenarios` を切る（本書を置いたブランチ）
- `proactive-dev`（japaneast）は Plan 3 のまま残っている。Task 9 の `azd up` は制作者に確認してから行う

## Global Constraints

- Python は 3.12（`requires-python = ">=3.12"`）。地域は `japaneast`
- キーと接続文字列を使わない。Container Apps の組み込み認証はクライアントシークレットなしで構成する（ID トークンだけを受け取る暗黙的フロー）。コンテナーレジストリの管理者ユーザーは無効にし、イメージはマネージド ID で取得する
- エージェントの ID には Cosmos DB のロールを一切付けない。BFF の ID には付ける（設計書 7.5 節）
- BFF の中の仮想の現在時刻は、必ず `StoredClock` から取る。`datetime.now()` を使ってよいのは、`set_virtual_now` に渡す実時間だけ
- エージェントへの要求に入れてよいのは `conversation`、`input`、`background` だけ（設計書 7.11 節 5）
- チャットの会話はチームに1本（設計書 7.11 節 4）
- `impact_notice` を `agent_mail` に書くのは、人が承認したときの BFF だけ（設計書 4.2 節）
- 配達前の通知（`delivered_at` が空）と、それにひもづくメッセージは、BFF も画面に出さない（Plan 2 の申し送り）
- 画面の文字、API のエラーの理由、道具の説明、指示文は日本語。登場するデータはすべて架空
- 画面ではブラウザの `alert` / `confirm` / `prompt` を使わない。確かめが要る操作（デモの作り直しなど）は画面の中で確かめる
- CDN からスクリプトを読まない。画面の依存は npm で入れ、版を固定する（`package-lock.json` を入れる）
- `azd provision`・`azd up`・`azd down` と Azure 上のデータを消す操作は、実行の前に制作者に確認する（スクリプトの作り直しは、デモのデータを消すことを使い方に明記する）

### 設計書の隙間を埋めた決定（実装者はこのとおりに作る）
1. **構成**: BFF と画面を1つのコンテナにする。BFF は `/api/*` を受け、それ以外は `proactive_web/static/` のビルド済みの画面を返す（見つからないパスは `index.html`）。Container Apps は `minReplicas: 0`、`maxReplicas: 1`
2. **サインインと人物**: サインインは Container Apps の組み込み認証。BFF は `X-MS-CLIENT-PRINCIPAL-NAME` を利用者として読み、なければ 401（`WEB_AUTH=off` のローカルだけ「local」とみなす）。誰として見るかは、API の `persona` 引数（`tanaka` / `sato` / `suzuki` / `takahashi`）で渡す。BFF は人物からチームを決め、ほかの値は 400「知らない人物です」。画面は選んだ人物を `localStorage` に覚える（読めなくても動く）
3. **チャットの会話 ID**: `team_settings.chat_conversation_id` に持つ。なければ最初のチャットで作って書く。シードの作り直しでは引き継がない（前のデモの会話を持ち越さないため）
4. **チャットの流れ**: BFF は、人の発言を `messages`（`role: human`、`author`: 人物 ID、`text`: 発言そのもの）に書き、決まった形のプロンプト（決定 5）を `background=True` で送り、`agent_runs` に `run-chat-<発言 ID>`（`state: running`、`detail: {kind: "chat", conversation_id, response_id, message_id}`）を作って戻る。返事の受け取りは、`GET /api/state` と CLI が `ChatService.sync` を呼んで行う。完了していれば `msg-reply-<発言 ID>`（`role: assistant`、`author: "agent"`）を作って記録を `done` にする。失敗なら同じ ID で `role: system` の「返事を作れませんでした（状態: <状態>）」を書く。10 分たっても終わらなければ、状態を `timeout` として同じく閉じる
5. **チャットのプロンプト**（そのまま使う）:
   ```
   チャット（発言 ID: {message_id}）
   {name_ja}（{チームの日本語名}、{role}）: {text}
   ```
6. **チャットの二重送信**: そのチームに `running` の `run-chat-*` があるあいだは、新しいチャットを受け付けない（HTTP 409「アシスタントが返事を書いています。少し待ってから送ってください」）。Functions の `reconcile_runs` は `detail.kind == "chat"` の記録を飛ばす（閉じるのは BFF だけ。tick が先に閉じると返事を書き写せなくなる）
7. **承認**: `POST /api/proposals/{id}/decision`（`{"persona", "action": "approve" | "reject", "draft"?}`）。決められるのは提案のチームの人物だけ（ほかは 403）。`pending` 以外は 409。承認では、`to_teams` の宛先ごとに `agent_mail` を ID `am-<提案 ID>-<宛先チーム>` で新規作成し（既にあれば飛ばす）、そのあとで提案の `status`・`decided_by`・`decided_at`（仮想の時刻）・`draft`（直した文）を etag 付きで書き換える。メールを先に書くので、途中で止まってももう一度押せば揃う。画面の「送る / 直す / 今回は送らない」は、`approve` / 下書きを直して `approve` / `reject`
8. **事前の承認**（設計書 7.5 節）: 自チームへのメッセージ（朝のまとめなど）は、もともと承認なしで届く。Plan 4 では新しい仕組みを作らず、README にそう書く
9. **画面の状態**: `GET /api/state?persona=` が1回で返す（決定 10 の形）。チャットの返事の受け取り（決定 4）もここで行う。画面は Web PubSub の合図を受けたら読み直し、合図がなくても 30 秒ごと（チャットの返事待ちのあいだは 3 秒ごと）に読み直す
10. **`/api/state` の形**: `now`、`release`（`{"id": "R3", "due_date", "days_left"}`）、`persona`、`team`、`team_label`、`people`（人物 ID → 日本語名）、`messages`（自チームの、見せてよいもの。古い順）、`priority_message_ids`（高橋だけ: 決定 11）、`proposals`（自チーム、ID → 文書）、`notifications`（配達済み。自チーム、統括は全チーム。ID → 文書）、`work`（`{"now", "planned", "done"}`。決定 12）、`watches`（自チーム）、`memories`（`[{"id", "text"}]`）、`settings`（`proactivity`、`quiet_start`、`quiet_end`）、`chat_busy`
11. **判断が必要な案件**（高橋の画面）: 統括のメッセージのうち、ひもづく通知の `classification` が `notify_now` のものを、会話欄の上に「判断が必要なこと」として先に並べる
12. **作業の見える化**: `now` は `running` の作業記録。`planned` は `scheduled` の作業記録、まだ実行していない `schedules`、次の朝 8:00（仮想の時刻）の「朝のまとめ（Routines）」（統括は「朝のブリーフィング（Routines）」）を時刻順に。`done` は `done` の作業記録の新しい順 20 件で、`detail.summary` を添える。統括は全チームの作業記録と予定を見る
13. **影響マップ**: `GET /api/map` が配置を返す。列は 0 車種、1 領域、2 要求と安全要求、3 仕様と信号、4 モデル、5 テスト。リリースとレビューは描かない。行は列ごとに、領域の順（車両統合制御、モーター制御、電池制御、機能安全、評価）→ ID の順。ノードの領域は `Graph.domain_team`。辺は「車種 → 領域」「領域 → その領域の要求と安全要求」と、`links`（上流 → 下流）。辺の両端の領域が違えば `cross_team: true`。アシスタントのいない領域は「アシスタント準備中」と表示する
14. **マップの光り方**（画面の側）: メッセージを選ぶと、その通知の起点を塗りつぶし、`impacted_ids` を赤枠、`highlight_ids` のほかのノードを通常、残りを薄くする。`cross_team_edges` の辺は赤い点線、ほかの辺は薄くする。何も選んでいなければ、チームの画面では自チームの領域を濃く、ほかを中くらいに、高橋の画面では全体を同じ濃さにする。領域は折りたためる
15. **グラフ**: `GET /api/files/{file_id}?persona=` は、その人物のチームで見せてよいメッセージの添付に `foundry-file:<file_id>` があるときだけ、プロジェクトの OpenAI クライアント（`project.get_openai_client().files.content(file_id)`）で取って返す。ないときは 404。PNG なら `image/png`
16. **画面への合図**: `GET /api/negotiate?persona=` が Web PubSub のクライアント用 URL を返す。参加するグループは人物のチーム（高橋は全チームの値）。BFF が `get_client_access_token(groups=…)` でグループを決める（画面に参加の操作をさせない）。Web PubSub が設定されていないローカルでは `{"url": null}` を返し、画面は読み直しの間隔だけで動く
17. **シナリオの再生**: `SCENARIO_ORDER` の全シナリオの手順を1列に並べ、`system` コンテナの文書 `scenario_progress`（`{"id", "vehicle_id", "next_index"}`）で次の手を覚える。「次へ」は、前提を確かめる → 仮想の時刻が手順の `at` より前なら時計を `at` に進める（戻さない）→ 手順を行う → `next_index` を進める、の順。前提が揃っていなければ（承認待ちの提案がない、チャットの返事待ち、時計の手順なのに調査が終わっていない）、時計も進み具合も変えずに `StepNotReady`（理由つき、HTTP 409）。時計の手順（`SET_CLOCK`）の前提は、`investigations` に `status: pending` がなく、`agent_runs` に `detail.kind != "chat"` の `running` がないこと（理由「調査が終わっていません（<ID>）」）。夜の調査が終わる前に朝へ進めると、エージェントが昼の時刻で通知を記録し、朝まで保留する筋書きが崩れるため。作り直し（`seed_store(reset=True)`）で `system` ごと消えるので、進み具合も最初に戻る
18. **シナリオ1の承認**: `StepKind.APPROVE`（`team`、`person_id` を持つ）を足し、s1 の手順に「11/18 08:20 田中が承認待ちの影響の連絡を送る」を、時計を 8:00 に進める手順と佐藤の発言のあいだに入れる。承認するのは、そのチームの `pending` の `impact_notice` のうち最も古いもの
19. **変更の手順**: `change_events` に変更を新規作成し（既にあれば飛ばす）、`artifacts` の該当データにも変更後の値を書く（`apply_changes`。`path` は `attributes.period_ms` のような `.` 区切り。`updated_at` は手順の時刻）。Functions は `artifacts` を書き換えない（Plan 2 の申し送り）
20. **ローカルでの確認**: `WEB_STORE=memory`、`WEB_AUTH=off` のとき、BFF はメモリーの Store にシードと「シナリオ1の朝」の状態（配達済みの通知、承認待ちの提案、提案つきのメッセージ）を入れ、チャットは決まった返事を返す偽物で動く。画面の確かめはこれで行う
21. **エージェントの指示文の追加**: 4体に「チャットで話しかけられたとき」、3チームに「チーフエンジニアに判断を仰ぐとき」を足す（Task 4 に文面）。設計書 5.3 節のシナリオ1の手順 6 で、統合制御のアシスタントが escalation を送るのに要る
22. **通知とメッセージを必ず結びつける**: 保留と非表示（決定 9、11、Plan 2 の `_held`）は、エージェントが `record_notification` を先に呼び、返った ID を `post_message` の `notification_id` に渡すことに依っている。investigate スキルの手順 8 を「通知を記録した調査で話しかけるときは、必ずその notification_id を渡す」に強め、統括の指示文の「判断が必要なことを上げるとき」を「`record_notification` で記録してから、その ID を付けて `post_message`」の順に直す（今は逆で、高橋の「判断が必要なこと」が空になる）

## Review Focus

1. **他チームの人物が提案を決めようとする**（佐藤として統合制御の下書きを「送る」）→ 403 で、メールは1通も書かない。テストは Task 3
2. **承認の二度押し、二つの画面からの同時の承認** → メールは宛先ごとに1通だけ、2回目は 409。テストは Task 3
3. **返事を書いている途中にチャットを送る** → 409 で、エージェントへの応答は1つしか起動しない。テストは Task 4
4. **夜間に記録された通知とそのメッセージ**（`delivered_at` が空）→ `/api/state` に出ない。配達されたら出る。テストは Task 2
5. **前提が揃う前にシナリオの「次へ」を押す**（承認待ちの提案がまだない）→ 409 と理由を返し、時計も進み具合も変えない。テストは Task 5
6. **夜の調査が終わる前に「次へ」を続けて押して朝へ進める** → 409「調査が終わっていません」で、時計は 21:10 のまま。テストは Task 5

---

## ファイル構成

```
pyproject.toml                          # members に "web" を足す
azure.yaml                              # web サービス（containerapp、リモートビルド）
core/src/vehicle_core/
  models.py                             # TeamSettings.chat_conversation_id
  scenarios.py                          # StepKind.APPROVE、s1 に承認の手順
  changes.py                            # 新規: apply_changes
functions/proactive_functions/
  memory_store.py                       # 新規: tests/fakes.py の MemoryStore を移す
  foundry_invoker.py                    # reconcile_runs が chat の記録を飛ばす
web/
  pyproject.toml                        # name = "proactive-web"
  Dockerfile                            # 画面のビルド → Python の実行
  proactive_web/
    settings.py                         # WEB_STORE、WEB_AUTH、各エンドポイント
    auth.py                             # 利用者（組み込み認証のヘッダー）
    personas.py                         # 4人の人物
    views.py                            # 画面の状態（純粋な関数）
    map_layout.py                       # マップの配置（純粋な関数）
    proposals.py                        # 承認と却下
    chat.py                             # ChatService、AgentChatClient、FoundryChatClient
    realtime.py                         # Web PubSub の URL
    files.py                            # グラフの取得
    scenario_runner.py                  # シナリオの再生
    scenario_checks.py                  # シナリオテストの期待値（純粋な判定）
    dev.py                              # ローカルの起動（決定 20）
    app.py                              # FastAPI のルートと依存
    static/                             # ビルド済みの画面（git 管理外）
  frontend/
    package.json, package-lock.json, vite.config.ts, tsconfig.json, index.html
    src/main.tsx, App.tsx, api.ts, types.ts, mapView.ts, mapView.test.ts, styles.css
    src/components/Header.tsx, Conversation.tsx, ProposalCard.tsx, ImpactMap.tsx, WorkPanel.tsx, SidePanel.tsx, AdminPanel.tsx
  tests/
agents/instructions/*.md                # チャット、判断を仰ぐとき
deploy/tests/test_agent_content.py      # 上の2つの節を確かめる
infra/modules/identity.bicep            # 名前の接頭辞を引数に
infra/modules/monitoring.bicep          # Log Analytics の ID を出力
infra/modules/webpubsub.bicep           # 所有者を配列に
infra/modules/foundry.bicep             # Web の ID のロール
infra/modules/web.bicep                 # 新規: レジストリ、環境、アプリ、サインイン用のアプリ登録、組み込み認証
infra/main.bicep
scripts/scenario.py                     # 新規: CLI（list / next / reset）
scripts/scenario_test.py                # 新規: シナリオテスト（Azure、本物の LLM）
README.md
```

---

### Task 1: 共有の部品（コアと Functions の小さな変更）

**Files:**
- Modify: `core/src/vehicle_core/models.py`、`core/src/vehicle_core/scenarios.py`
- Create: `core/src/vehicle_core/changes.py`、`core/tests/test_changes.py`
- Create: `functions/proactive_functions/memory_store.py`
- Modify: `functions/tests/fakes.py`（`MemoryStore` は移した先から import して再公開する）、`functions/proactive_functions/foundry_invoker.py`
- Test: `core/tests/test_scenarios.py`、`core/tests/test_models.py`、`functions/tests/test_foundry_invoker.py`

**Interfaces:**
- Produces: `TeamSettings.chat_conversation_id: str | None = None`
- Produces: `StepKind.APPROVE = "approve"`。s1 の手順は `[CHANGE 17 21:10, SET_CLOCK 18 08:00, APPROVE 18 08:20 (integrated_control, tanaka), HUMAN_SAYS 08:40 sato, HUMAN_SAYS 08:50 tanaka]`
- Produces: `vehicle_core.changes.apply_changes(doc: dict, changes: list[FieldChange], at: datetime) -> dict`（新しい辞書を返す。元は変えない）
- Produces: `proactive_functions.memory_store.MemoryStore`（`Store` プロトコル、`_etag` 付き。中身は今の `tests/fakes.py` と同じ）

- [ ] **Step 1: 失敗するテストを書く**

```python
# core/tests/test_changes.py
def test_apply_changes_sets_nested_path_and_updated_at():
    doc = {"id": "SIG-BrkPedalPos", "attributes": {"period_ms": 10, "sender": "VCU"}, "updated_at": "x"}
    at = datetime(2026, 11, 17, 21, 10, tzinfo=JST)
    out = apply_changes(doc, [FieldChange(path="attributes.period_ms", before=10, after=20)], at)
    assert out["attributes"] == {"period_ms": 20, "sender": "VCU"}
    assert out["updated_at"] == at.isoformat()
    assert doc["attributes"]["period_ms"] == 10  # 元の文書は変えない

def test_apply_changes_sets_top_level_field():
    out = apply_changes({"id": "SPEC-BRK-04", "description": "旧"}, [FieldChange(path="description", before="旧", after="新")], AT)
    assert out["description"] == "新"

def test_apply_changes_creates_missing_parent():
    out = apply_changes({"id": "X"}, [FieldChange(path="attributes.a", before=None, after=1)], AT)
    assert out["attributes"] == {"a": 1}
```

```python
# core/tests/test_scenarios.py に足す
def test_s1_has_approve_step_between_morning_and_replies():
    kinds = [s.kind for s in SCENARIOS["s1_signal_period"].steps]
    assert kinds == ["change", "set_clock", "approve", "human_says", "human_says"]
    approve = SCENARIOS["s1_signal_period"].steps[2]
    assert approve.team == Team.INTEGRATED_CONTROL and approve.person_id == "tanaka"
    assert approve.at == datetime(2026, 11, 18, 8, 20, tzinfo=JST)
```

```python
# core/tests/test_models.py に足す
def test_team_settings_chat_conversation_id_defaults_to_none():
    assert TeamSettings(id="ts-x", team=Team.EVALUATION).chat_conversation_id is None
```

```python
# functions/tests/test_foundry_invoker.py に足す
def test_reconcile_runs_skips_chat_runs():
    # detail.kind == "chat" の running の記録は、応答が completed でも閉じない（決定 6）
    store = MemoryStore()
    store.create("agent_runs", run_doc("run-chat-msg-1", started=NOW - timedelta(minutes=5),
                                       detail={"kind": "chat", "response_id": "resp-1"}))
    client = FakeResponses(status="completed")
    assert reconcile_runs(store, lambda team: client, NOW) == []
    assert store.get("agent_runs", "run-chat-msg-1")["state"] == "running"
    assert client.looked_up == []
```

（`run_doc`、`FakeResponses` は同じテストファイルにある既存の補助を使う。名前が違えば合わせる）

- [ ] **Step 2: 失敗を確かめる**

Run: `cd core && uv run pytest -q tests/test_changes.py tests/test_scenarios.py tests/test_models.py` と `cd functions && uv run pytest -q tests/test_foundry_invoker.py`
Expected: `apply_changes` がない、手順の数が違う、`chat_conversation_id` がない、chat の記録が閉じられる、で FAIL

- [ ] **Step 3: 実装する**
  - `TeamSettings` に `chat_conversation_id`、`StepKind.APPROVE` と s1 の手順（`_approve(at, team, person_id)` の補助を足す）
  - `apply_changes`: `copy.deepcopy` してから `.` で辿り、途中がなければ空の辞書を作る
  - `MemoryStore` を `proactive_functions/memory_store.py` に移し、`functions/tests/fakes.py` は `from proactive_functions.memory_store import MemoryStore` にする
  - `reconcile_runs` は `run.detail.get("kind") == "chat"` を飛ばす
  - 既存のテストで s1 の手順の数や順番に依るものがあれば直す（`steps[0]` の変更イベントは変わらない）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd core && uv run pytest -q` と `cd functions && uv run pytest -q`
Expected: すべて PASS

- [ ] **Step 5: Commit** — `git commit -m "feat(core): シナリオ1の承認の手順、変更の適用、チャットの会話 ID を足す"`

---

### Task 2: web パッケージと画面の状態（読み取り）

**Files:**
- Modify: `pyproject.toml`（`members = ["core", "functions", "deploy", "web"]`）、`.gitignore`（`web/proactive_web/static/`、`web/frontend/node_modules/`）
- Create: `web/pyproject.toml`、`web/proactive_web/{__init__,settings,auth,personas,views,map_layout,app,dev}.py`
- Test: `web/tests/test_views.py`、`web/tests/test_map_layout.py`、`web/tests/test_app_read.py`

**Interfaces:**
- Consumes: `MemoryStore`、`CosmosStore`、`StoredClock`、`vehicle_core.seed.build_dataset`、`vehicle_core.impact.Graph`
- Produces: `personas.PERSONAS: dict[str, Persona]`（`Persona(id, name_ja, team: Team, role)`、シードの人物から作る）、`personas.persona_or_400(id: str) -> Persona`
- Produces: `views.visible_messages(messages: list[dict], notifications_by_id: dict[str, dict]) -> list[dict]`
- Produces: `views.build_state(store: Store, persona: Persona, now: datetime, memories: list[dict]) -> dict`（決定 10 の形。`chat_busy` は `running` の `run-chat-*` があるか）
- Produces: `map_layout.build_map(artifacts: list[Artifact]) -> dict`（`{"nodes": [{"id", "label", "type", "column", "row", "group"}], "edges": [{"source", "target", "cross_team"}], "groups": [{"team", "label", "has_assistant"}]}`）
- Produces: `app.MemoryReader` プロトコル `list(team: str) -> list[dict]`（`[{"id", "text"}]`）と実装 `FoundryMemoryReader(project_endpoint, credential, store_name)`（Plan 3 の `FoundryMemoryBackend.search(team, None)` を使う）
- Produces: `app.create_app(deps: Deps | None = None) -> FastAPI`。`Deps` は `store`、`clock`（`now()`）、`memory`（`MemoryReader` または None）、`chat`、`realtime`、`files`、`system_now`。`None` なら設定から作る（Task 3〜5 で足す項目は、それまでは None でよい）
- Produces: ルート `GET /api/me`（`{"user", "personas"}`）、`GET /api/state?persona=`、`GET /api/map`

- [ ] **Step 1: 失敗するテストを書く**

```python
# web/tests/test_views.py
def test_held_notification_and_its_message_are_hidden_until_delivered():  # Review Focus 4
    store = MemoryStore(); seed(store)
    store.create("notifications", notification("n-1", team="integrated_control", delivered_at=None))
    store.create("messages", message("m-1", team="integrated_control", notification_id="n-1"))
    store.create("messages", message("m-2", team="integrated_control"))
    state = build_state(store, PERSONAS["tanaka"], NIGHT, [])
    assert [m["id"] for m in state["messages"]] == ["m-2"]
    assert "n-1" not in state["notifications"]
    store.upsert("notifications", store.get("notifications", "n-1") | {"delivered_at": MORNING.isoformat()})
    state = build_state(store, PERSONAS["tanaka"], MORNING, [])
    assert [m["id"] for m in state["messages"]] == ["m-1", "m-2"]  # 古い順

def test_team_persona_sees_only_own_team_and_chief_sees_all_notifications():
    ...  # 統合制御と評価に配達済みの通知を1件ずつ → 田中は1件、高橋は2件。messages は両者とも自チームだけ

def test_release_days_left_uses_virtual_today():
    assert build_state(store, PERSONAS["tanaka"], datetime(2026, 11, 17, 18, 0, tzinfo=JST), [])["release"] == \
        {"id": "R3", "due_date": "2026-11-30", "days_left": 13}

def test_priority_messages_are_chief_messages_linked_to_notify_now():
    ...  # 統括の通知 notify_now と digest にひもづくメッセージ → priority_message_ids は前者だけ。田中は常に空

def test_work_groups_runs_and_plans():
    ...  # running / scheduled / done の作業記録と未実行の schedules →
    # now に running、planned に scheduled と schedules と「朝のまとめ（Routines）」（翌朝 8:00）が時刻順、done は新しい順で summary つき

def test_agent_client_id_is_not_exposed():
    assert "agent_client_id" not in json.dumps(build_state(store, PERSONAS["takahashi"], NOW, []))
```

```python
# web/tests/test_map_layout.py
def test_columns_follow_vehicle_domain_requirement_spec_model_test():
    m = build_map(build_dataset().artifacts)
    col = {n["id"]: n["column"] for n in m["nodes"]}
    assert col["VEHICLE"] == 0 and col["DOMAIN-integrated_control"] == 1
    assert col["REQ-112"] == 2 and col["SR-01"] == 2
    assert col["SPEC-BRK-04"] == 3 and col["SIG-BrkPedalPos"] == 3
    assert col["MDL-RegenCoord"] == 4 and col["TC-HILS-031"] == 5
    assert "R3" not in col and "RV-01" not in col

def test_cross_team_edge_from_signal_to_motor_model():
    edges = {(e["source"], e["target"]): e["cross_team"] for e in build_map(build_dataset().artifacts)["edges"]}
    assert edges[("SIG-BrkPedalPos", "MDL-MotorTq")] is True
    assert edges[("SIG-BrkPedalPos", "MDL-RegenCoord")] is False

def test_rows_are_grouped_by_domain_order():
    ...  # 列 5 で TC-HILS-031（統合制御の領域）が TC-HILS-012（モーター制御）より上

def test_groups_mark_teams_without_assistant():
    groups = {g["team"]: g["has_assistant"] for g in build_map(build_dataset().artifacts)["groups"]}
    assert groups["integrated_control"] is True and groups["battery_control"] is False
```

```python
# web/tests/test_app_read.py（TestClient、Deps はメモリーの Store と固定の時計）
def test_api_requires_signed_in_user_when_auth_is_on(): ...      # ヘッダーなし → 401
def test_state_rejects_unknown_persona(): ...                    # persona=nobody → 400「知らない人物です」
def test_me_lists_four_personas_with_teams(): ...
def test_unknown_path_serves_index_html(tmp_path): ...           # static に index.html を置き、/foo → index.html
```

- [ ] **Step 2: 失敗を確かめる** — Run: `cd web && uv run pytest -q` / Expected: import できずに FAIL

- [ ] **Step 3: 実装する**
  - `web/pyproject.toml`: 依存は `vehicle-core`、`proactive-functions`（ワークスペース）、`fastapi`、`uvicorn[standard]`、`azure-ai-projects>=2.10`、`azure-identity`、`azure-messaging-webpubsubservice`。開発用に `pytest`、`httpx`
  - `settings.py`: `WEB_STORE`（`cosmos` | `memory`、既定 `cosmos`）、`WEB_AUTH`（`easyauth` | `off`、既定 `easyauth`）、`COSMOS_ENDPOINT`、`COSMOS_DATABASE`、`FOUNDRY_PROJECT_ENDPOINT`、`MEMORY_STORE_NAME`、`WEBPUBSUB_ENDPOINT`、`WEBPUBSUB_HUB`。`cosmos` のときは Cosmos の2つが必須
  - `views.py`: 決定 9〜12。見せてよいかの判定は `publisher._held` と同じ規則（通知は `delivered_at` があるもの、メッセージはひもづく通知が配達済みか、通知を持たないもの）
  - `map_layout.py`: 決定 13
  - `app.py`: ルートは `persona_or_400` で人物を決め、`deps.clock.now()` を使う。`/api/state` は Task 4 で `chat.sync` を呼ぶようにする（この時点では呼ばない）
  - `dev.py`: 決定 20。`python -m proactive_web.dev` で `127.0.0.1:8000` に起動する。シナリオ1の朝の状態は `analyze_impact(graph, "SIG-BrkPedalPos")` から作る（通知の根拠がコードと一致するように）

- [ ] **Step 4: 通ることを確かめる** — Run: `cd web && uv run pytest -q` / Expected: PASS

- [ ] **Step 5: Commit** — `git commit -m "feat(web): BFF の読み取り（画面の状態、マップの配置、人物）を足す"`

---

### Task 3: 承認、設定、画面への合図、グラフ

**Files:**
- Create: `web/proactive_web/{proposals,realtime,files}.py`
- Modify: `web/proactive_web/app.py`
- Test: `web/tests/test_proposals.py`、`web/tests/test_app_write.py`

**Interfaces:**
- Produces: `proposals.DecisionError(status: int, reason: str)`、`proposals.decide_proposal(store: Store, proposal_id: str, persona: Persona, action: Literal["approve", "reject"], draft: str | None, now: datetime) -> dict`（書き換えた提案を返す）
- Produces: `realtime.RealtimeUrls` プロトコル `client_url(groups: list[str]) -> str | None`、実装 `WebPubSubUrls(endpoint, hub, credential)`、`NoRealtime`
- Produces: `files.FileSource` プロトコル `content(file_id: str) -> bytes`、実装 `FoundryFiles(project_endpoint, credential)`、`files.allowed_file_ids(visible_messages: list[dict]) -> set[str]`
- Produces: ルート `POST /api/proposals/{id}/decision`、`PUT /api/settings`（`{"persona", "proactivity"}`）、`GET /api/negotiate?persona=`、`GET /api/files/{file_id}?persona=`

- [ ] **Step 1: 失敗するテストを書く**

```python
# web/tests/test_proposals.py
def test_approve_writes_one_mail_per_team_then_marks_approved():
    store = with_proposal("prop-1", team="integrated_control", to_teams=["motor_control", "evaluation"])
    out = decide_proposal(store, "prop-1", PERSONAS["tanaka"], "approve", None, NOW)
    assert out["status"] == "approved" and out["decided_by"] == "tanaka" and out["decided_at"] == NOW.isoformat()
    mails = sorted(m["id"] for m in store.query("agent_mail"))
    assert mails == ["am-prop-1-evaluation", "am-prop-1-motor_control"]
    m = store.get("agent_mail", "am-prop-1-motor_control")
    assert m["kind"] == "impact_notice" and m["from_team"] == "integrated_control" and m["thread_id"] == "th-1"

def test_approve_with_edited_draft_sends_edited_text():
    out = decide_proposal(store, "prop-1", PERSONAS["tanaka"], "approve", "直した本文", NOW)
    assert out["draft"] == "直した本文"
    assert store.get("agent_mail", "am-prop-1-motor_control")["body"] == "直した本文"

def test_other_team_persona_cannot_decide():  # Review Focus 1
    with pytest.raises(DecisionError) as e:
        decide_proposal(store, "prop-1", PERSONAS["sato"], "approve", None, NOW)
    assert e.value.status == 403 and store.query("agent_mail") == []

def test_second_decision_is_conflict_and_writes_no_more_mail():  # Review Focus 2
    decide_proposal(store, "prop-1", PERSONAS["tanaka"], "approve", None, NOW)
    with pytest.raises(DecisionError) as e:
        decide_proposal(store, "prop-1", PERSONAS["tanaka"], "approve", None, NOW)
    assert e.value.status == 409 and len(store.query("agent_mail")) == 2

def test_retry_after_mail_written_but_status_not_saved_completes_without_duplicates():
    store.create("agent_mail", existing_mail("am-prop-1-motor_control"))  # 途中で止まった状態
    decide_proposal(store, "prop-1", PERSONAS["tanaka"], "approve", None, NOW)
    assert len(store.query("agent_mail")) == 2

def test_reject_writes_no_mail():
    assert decide_proposal(store, "prop-1", PERSONAS["tanaka"], "reject", None, NOW)["status"] == "rejected"
    assert store.query("agent_mail") == []

def test_empty_edited_draft_is_rejected():
    with pytest.raises(DecisionError) as e:
        decide_proposal(store, "prop-1", PERSONAS["tanaka"], "approve", "  ", NOW)
    assert e.value.status == 422
```

```python
# web/tests/test_app_write.py
def test_decision_route_maps_errors_to_status_and_japanese_reason(): ...   # 403 と detail の日本語
def test_settings_updates_own_team_proactivity_only(): ...                 # 鈴木が "important_only" → ts-evaluation だけ変わる。不正な値は 422
def test_negotiate_groups_for_team_and_chief(): ...                        # 田中 → ["integrated_control"]、高橋 → Team の全値。NoRealtime → {"url": None}
def test_file_is_served_only_when_attached_to_visible_message(): ...       # 添付にある ID → 200 image/png、ない ID → 404、配達前の通知のメッセージの添付 → 404
```

- [ ] **Step 2: 失敗を確かめる** — Run: `cd web && uv run pytest -q tests/test_proposals.py tests/test_app_write.py` / Expected: FAIL

- [ ] **Step 3: 実装する** — 決定 7、15、16。提案の書き換えで etag が合わなければ読み直し、ほかの人が決めていたら 409。PNG の判定は先頭8バイト（`\x89PNG\r\n\x1a\n`）

- [ ] **Step 4: 通ることを確かめる** — Run: `cd web && uv run pytest -q` / Expected: PASS

- [ ] **Step 5: Commit** — `git commit -m "feat(web): 承認、話しかける頻度の設定、画面への合図、グラフの取得を足す"`

---

### Task 4: チャット（BFF とエージェントの指示文）

**Files:**
- Create: `web/proactive_web/chat.py`、`web/tests/test_chat.py`
- Modify: `web/proactive_web/app.py`（`POST /api/chat`、`/api/state` で `sync`）
- Modify: `agents/instructions/{chief_engineer,integrated_control,motor_control,evaluation}.md`、`agents/skills/investigate/SKILL.md`、`deploy/tests/test_agent_content.py`

**Interfaces:**
- Produces: `chat.AgentChatClient` プロトコル: `create_conversation(team: Team) -> str`、`start_response(team: Team, conversation_id: str, prompt: str) -> str`、`get_response(team: Team, response_id: str) -> tuple[str, str]`（状態、`output_text`）
- Produces: `chat.FoundryChatClient(project_endpoint, credential)`（チームごとに `project.get_openai_client(agent_name=agent_name(team))` を作って持つ。送るのは `conversation`、`input`、`background=True` だけ）
- Produces: `chat.ChatBusy`、`chat.ChatFailed`、`chat.chat_prompt(message_id: str, persona: Persona, text: str) -> str`（決定 5）
- Produces: `chat.ChatService(store: Store, client: AgentChatClient, now: Callable[[], datetime])` の `busy(team: Team) -> bool`、`send(persona: Persona, text: str) -> str`（発言の ID）、`sync(team: Team | None = None) -> list[str]`（閉じた記録の ID）
- Produces: ルート `POST /api/chat`（`{"persona", "text"}` → `{"message_id"}`。`ChatBusy` は 409、空や 2000 文字を超える本文は 422、`ChatFailed` は 502）

- [ ] **Step 1: 失敗するテストを書く**

```python
# web/tests/test_chat.py（FakeChatClient: 呼ばれた引数を記録し、状態と本文を決めて返す）
def test_send_writes_human_message_starts_background_response_and_running_run():
    mid = service.send(PERSONAS["sato"], "今週は v2.1 で手一杯です")
    msg = store.get("messages", mid)
    assert msg["role"] == "human" and msg["author"] == "sato" and msg["text"] == "今週は v2.1 で手一杯です"
    assert client.prompts == [f"チャット（発言 ID: {mid}）\n佐藤（モーター制御、モータートルク制御の主担当）: 今週は v2.1 で手一杯です"]
    run = store.get("agent_runs", f"run-chat-{mid}")
    assert run["state"] == "running" and run["detail"]["kind"] == "chat"

def test_conversation_is_created_once_per_team_and_saved():
    service.send(PERSONAS["tanaka"], "a"); service.sync(); service.send(PERSONAS["tanaka"], "b")
    assert client.conversations_created == 1
    assert store.get("team_settings", "ts-integrated_control")["chat_conversation_id"] == "conv-1"

def test_send_while_reply_running_is_busy_and_starts_nothing():  # Review Focus 3
    service.send(PERSONAS["tanaka"], "a")
    with pytest.raises(ChatBusy):
        service.send(PERSONAS["tanaka"], "b")
    assert len(client.prompts) == 1

def test_sync_writes_reply_and_closes_run_once():
    mid = service.send(PERSONAS["tanaka"], "a"); client.finish("completed", "返事です")
    assert service.sync() == [f"run-chat-{mid}"]
    reply = store.get("messages", f"msg-reply-{mid}")
    assert reply["role"] == "assistant" and reply["author"] == "agent" and reply["text"] == "返事です"
    assert store.get("agent_runs", f"run-chat-{mid}")["state"] == "done"
    assert service.sync() == []

def test_sync_writes_system_message_on_failure_and_timeout():
    ...  # failed → role system「返事を作れませんでした（状態: failed）」。in_progress のまま 10 分 → 状態 timeout で同じく閉じる

def test_sync_leaves_in_progress_run_open(): ...
def test_empty_or_too_long_text_is_rejected(): ...   # "  " と 2001 文字 → ValueError、何も書かない
def test_start_failure_raises_chat_failed_and_leaves_no_running_run(): ...
```

```python
# deploy/tests/test_agent_content.py に足す
def test_every_instruction_explains_chat_replies():
    for team in AGENT_TEAMS:
        text = instruction(team)
        assert "## チャットで話しかけられたとき" in text
        assert "source_message_id" in text and "post_message" in text

def test_team_instructions_explain_escalation():
    for team in AGENT_TEAMS - {Team.CHIEF_ENGINEER}:
        text = instruction(team)
        assert "## チーフエンジニアに判断を仰ぐとき" in text and "escalation" in text

def test_messages_are_linked_to_recorded_notifications():  # 決定 22
    skill = skill_text("investigate")
    assert "必ずその notification_id を渡す" in skill
    chief = instruction(Team.CHIEF_ENGINEER)
    section = chief.split("## 判断が必要なことを上げるとき")[1].split("##")[0]
    assert section.index("record_notification") < section.index("post_message")
```

（`instruction`、`skill_text` は既存のテストの補助を使う。名前が違えば合わせる）

- [ ] **Step 2: 失敗を確かめる** — Run: `cd web && uv run pytest -q tests/test_chat.py` と `cd deploy && uv run pytest -q tests/test_agent_content.py` / Expected: FAIL

- [ ] **Step 3: 実装する**
  - `chat.py`: 決定 3〜6。`sync` は応答の状態を読めなかった記録をログに残して飛ばす。メッセージの作成は `Conflict` を無視する（二つの読み直しが同時に閉じても二重にならない）
  - `app.py`: `/api/state` は、そのチーム（高橋は統括）の `chat_busy` が真のときだけ `sync(team)` を呼んでから状態を作る
  - `dev.py`: チャットは、すぐに completed になり「（ローカルの確認用の返事です）」を返す偽物の `AgentChatClient` にする
  - 指示文: 4体の「チームとの会話」の前に次の節を足す（統括は「チーフエンジニアとの会話」の前）

    ```markdown
    ## チャットで話しかけられたとき

    人の発言は、「チャット（発言 ID: msg-…）」の次の行に「名前（チーム、役割）: 本文」の形で届く。

    - 返事は、最後に文章で書く。その文章がそのまま画面の会話に出る。同じ返事を `post_message` で書かない
    - 人の返答を他チームに届けるとき（`send_mail` の種類 human_reply）は、`source_message_id` に発言 ID を、`body` に本文をそのまま（「名前（…）:」を除いて）入れる
    - 返事は短く、データの ID を添える
    ```
  - investigate スキルの手順 8 を次にする: 「8. チームに話しかける場合は `post_message` で書く。通知を記録した調査で話しかけるときは、必ずその notification_id を渡す（渡さないと、静かな時間帯でもすぐ画面に出てしまう）。下書きと結びつけるときは proposal_id も渡す」
  - 統括の指示文の「判断が必要なことを上げるとき」の2文目を次にする: 「`record_notification` で notify_now として記録し、返った ID を notification_id に付けて、次の形で `post_message` に書く。」
  - 3チームの指示文の「統括から尋ねられたとき」の前に次の節を足す

    ```markdown
    ## チーフエンジニアに判断を仰ぐとき

    影響の連絡のスレッドで、相手のチームの人が「対応できない」と返し（human_reply の stance が cannot）、自チームの人も譲れないと言ったときは、`send_mail` で種類 escalation を chief_engineer に送る。thread_id はそのスレッドのものにする。本文には、起点と影響を受けるデータの ID、両チームの人の言い分、考えられる選択肢を書く。どの選択肢がよいかは書かない。
    ```

- [ ] **Step 4: 通ることを確かめる** — Run: `cd web && uv run pytest -q`、`cd deploy && uv run pytest -q` / Expected: PASS（`test_tool_names_in_content_exist_in_registry` も通る）

- [ ] **Step 5: Commit** — `git commit -m "feat(web): チャットを足し、エージェントにチャットの返事と判断の依頼の仕方を教える"`

---

### Task 5: シナリオの再生（BFF の管理用ルートと CLI）

**Files:**
- Create: `web/proactive_web/scenario_runner.py`、`web/tests/test_scenario_runner.py`、`scripts/scenario.py`
- Modify: `web/proactive_web/app.py`

**Interfaces:**
- Consumes: `decide_proposal`、`ChatService`、`apply_changes`、`set_virtual_now`、`seed_store`、`SCENARIOS`、`SCENARIO_ORDER`
- Produces: `scenario_runner.StepNotReady(reason: str)`、`scenario_runner.step_summary(step: ScenarioStep, people: dict[str, str]) -> str`
- Produces: `scenario_runner.ScenarioRunner(store: Store, chat: ChatService, system_now: Callable[[], datetime])` の `steps() -> list[dict]`（`{"index", "scenario_id", "scenario_title", "kind", "at", "summary", "done"}`）、`next() -> dict`（行った手順の `steps()` の要素）、`reset() -> None`
- Produces: ルート `GET /api/admin/steps`、`POST /api/admin/next`、`POST /api/admin/reset`、`POST /api/admin/clock`（`{"at": ISO 8601}`。戻すことも許す）。どれもサインインした人なら使える
- Produces: CLI `uv run --package proactive-web python scripts/scenario.py list | next [--wait] | reset`（`--wait` は人の発言の手順で、返事が書き写されるまで `sync` を5秒ごとに呼ぶ。上限5分）

- [ ] **Step 1: 失敗するテストを書く**

```python
# web/tests/test_scenario_runner.py（MemoryStore にシード、FakeChatClient、実時間は固定）
def test_first_step_moves_clock_to_change_time_and_writes_event_and_artifact():
    runner.next()
    assert StoredClock(store, FixedSystem(REAL)).now() == datetime(2026, 11, 17, 21, 10, tzinfo=JST)
    assert store.get("change_events", "ce-s1-1") is not None
    assert store.get("artifacts", "SIG-BrkPedalPos")["attributes"]["period_ms"] == 20
    assert [s["done"] for s in runner.steps()][:2] == [True, False]

def test_clock_is_never_moved_backwards(): ...   # 仮想の時刻を手順より後にしておく → 時計はそのまま、手順は行う

def test_approve_step_without_pending_proposal_is_not_ready_and_changes_nothing():  # Review Focus 5
    runner.next(); runner.next()  # 変更、8:00
    clock_before = store.get("system", "clock")["offset_seconds"]
    with pytest.raises(StepNotReady, match="承認待ち"):
        runner.next()
    assert store.get("system", "clock")["offset_seconds"] == clock_before
    assert runner.steps()[2]["done"] is False

def test_clock_step_waits_for_running_investigation():  # Review Focus 6
    runner.next()  # 21:10 の変更
    store.create("agent_runs", run_doc("run-inv-x", state="running", detail={"investigation_id": "x"}))
    with pytest.raises(StepNotReady, match="調査が終わっていません"):
        runner.next()
    assert StoredClock(store, FixedSystem(REAL)).now() == datetime(2026, 11, 17, 21, 10, tzinfo=JST)
    store.upsert("agent_runs", store.get("agent_runs", "run-inv-x") | {"state": "done"})
    runner.next()  # 終われば進める

def test_clock_step_waits_for_pending_investigation_but_not_for_chat_runs(): ...

def test_approve_step_approves_oldest_pending_impact_notice_as_tanaka(): ...
def test_human_says_step_sends_chat_as_person(): ...      # FakeChatClient のプロンプトに「佐藤（モーター制御、…）: 今週は…」
def test_human_says_step_is_not_ready_while_chat_busy(): ...
def test_reset_clears_progress_and_restores_seed_clock(): ...
def test_step_summary_is_japanese():
    assert step_summary(SCENARIOS["s1_signal_period"].steps[0], PEOPLE) == \
        "11/17 21:10 田中が SIG-BrkPedalPos の attributes.period_ms を 10 から 20 に変える"
    assert step_summary(SCENARIOS["s1_signal_period"].steps[2], PEOPLE) == "11/18 08:20 田中が承認待ちの影響の連絡を送る"
```

（ほかの種類の要約: 時計「11/18 08:00 まで時計を進める」、試験結果「11/18 10:00 TC-HILS-031 の試験結果（fail）が入る」、人の発言「11/18 08:40 佐藤: <本文>」）

- [ ] **Step 2: 失敗を確かめる** — Run: `cd web && uv run pytest -q tests/test_scenario_runner.py` / Expected: FAIL

- [ ] **Step 3: 実装する** — 決定 17〜19。進み具合の書き換えは etag 付き（同時に2回押されたら片方は 409「ほかの操作と重なりました」）。CLI は `scripts/_azd.py` の `cosmos_store` と `FoundryChatClient(DefaultAzureCredential)` を使う。`reset` の使い方の説明に「Azure 上のデモのデータを消して作り直す」と書く

- [ ] **Step 4: 通ることを確かめる** — Run: `cd web && uv run pytest -q` / Expected: PASS

- [ ] **Step 5: Commit** — `git commit -m "feat(web): シナリオを1手ずつ進める仕組み（管理用のルートと CLI）を足す"`

---

### Task 6: 画面（React）

**Files:**
- Create: `web/frontend/` 一式（ファイル構成のとおり）
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 2〜5 のルートと、`/api/state`・`/api/map` の形
- Produces: `npm run build` が `web/proactive_web/static/` に出力する。`npm test` が Vitest を動かす
- Produces: `mapView.ts` の `nodeTone(nodeId: string, group: string, sel: Selection | null, view: ViewMode) -> "origin" | "impacted" | "context" | "dim" | "own" | "other" | "even"`、`edgeTone(source: string, target: string, sel: Selection | null) -> "cross" | "dim" | "normal"`、`visibleNodes(nodes, collapsed: Set<string>)`（`Selection = {origin: string | null, impacted: Set<string>, highlight: Set<string>, cross: Set<string>}`、`ViewMode = {team: string, chief: boolean}`）

- [ ] **Step 1: 失敗するテストを書く**

```ts
// web/frontend/src/mapView.test.ts
test("origin is filled, impacted is red, other highlight is context, rest is dim", () => {
  const sel = selection({ origin: "SIG-BrkPedalPos", impacted: ["MDL-MotorTq"], highlight: ["SPEC-BRK-04", "SIG-BrkPedalPos", "MDL-MotorTq"] });
  expect(nodeTone("SIG-BrkPedalPos", "integrated_control", sel, TEAM)).toBe("origin");
  expect(nodeTone("MDL-MotorTq", "motor_control", sel, TEAM)).toBe("impacted");
  expect(nodeTone("SPEC-BRK-04", "integrated_control", sel, TEAM)).toBe("context");
  expect(nodeTone("REQ-301", "battery_control", sel, TEAM)).toBe("dim");
});
test("without selection, team view emphasizes own domain and chief view is even", () => {
  expect(nodeTone("REQ-112", "integrated_control", null, TEAM)).toBe("own");
  expect(nodeTone("REQ-201", "motor_control", null, TEAM)).toBe("other");
  expect(nodeTone("REQ-201", "motor_control", null, CHIEF)).toBe("even");
});
test("cross-team edges in the selection are dashed red", () => {
  expect(edgeTone("SIG-BrkPedalPos", "MDL-MotorTq", sel)).toBe("cross");
  expect(edgeTone("REQ-301", "SPEC-BAT-02", sel)).toBe("dim");
});
test("collapsed domain hides its nodes but keeps the domain node", () => { ... });
```

- [ ] **Step 2: 失敗を確かめる** — Run: `cd web/frontend && npm install && npm test` / Expected: FAIL

- [ ] **Step 3: 実装する**
  - 依存の版: `react@18.3.1`、`react-dom@18.3.1`、`vite@5.4.11`、`@vitejs/plugin-react@4.3.4`、`typescript@5.6.3`、`vitest@2.1.8`、`@types/react@18.3.12`、`@types/react-dom@18.3.1`。開発中は Vite の proxy で `/api` を `127.0.0.1:8000` に回す
  - 画面の作り（設計書 5.1 節、決定 9〜16）:
    - 上部: 車種名「架空SUV」、「R3 まで あと N 日」、仮想の時刻、人物の切り替え（4人、チーム名つき）、「デモの操作」を開くボタン
    - 左（会話）: 高橋は「判断が必要なこと」を先頭に。メッセージは送り手（人物名 / 「<チーム>のアシスタント」）と時刻つき。`proposal_id` があれば承認カード（下書き、宛先、「送る」「直す」「今回は送らない」、決まったあとは結果と決めた人）。`foundry-file:` の添付は `<img src="/api/files/<ID>?persona=…">`。下に入力欄（返事待ちのあいだは送れず「返事を書いています…」）
    - 中央（マップ）: SVG。列の見出し「車種 / 領域 / 要求 / 仕様・信号 / モデル / テスト」。決定 14 の光り方（塗りつぶし、赤枠、赤い点線、薄く）。領域ノードを押すと折りたたむ。下に「アシスタントの作業」（いま / 予定 / 完了）
    - 右（見張りと設定）: 見張りの一覧（説明と「すぐ / 朝まとめて」）、話しかける頻度（止める / 重要だけ / ふつう / こまめに）、覚えていること（Memory の項目）。追加と削除は会話で行うと書き添える
    - 「デモの操作」: 手順の一覧（済んだものに印）、「次へ」、時計の表示、「デモを最初からやり直す」（押すと画面の中で「Azure 上のデモのデータを消して作り直します」と確かめてから実行）。409 の理由はそのまま表示する
  - 画面への合図: `/api/negotiate` の URL に `WebSocket` でつなぎ、メッセージを受けたら 500ms まとめて `/api/state` を読み直す。切れたら 10 秒後につなぎ直す
  - 文字はすべて日本語。幅 1280px で3区画が横に並び、狭い幅では縦に並ぶ

- [ ] **Step 4: 通ることを確かめ、画面を見る**
  - Run: `cd web/frontend && npm test && npm run build` / Expected: PASS、`web/proactive_web/static/index.html` ができる
  - Run: `WEB_STORE=memory WEB_AUTH=off uv run --package proactive-web python -m proactive_web.dev` を裏で動かし、ブラウザ（Playwright）で `http://127.0.0.1:8000/` を開く
  - Expected（スクリーンショットで確かめる）: 田中の画面に提案つきのメッセージと承認カードが出る。メッセージを押すと SIG-BrkPedalPos が塗りつぶし、MDL-MotorTq が赤枠、その間の辺が赤い点線になる。佐藤に切り替えると会話が変わる。「直す」で下書きを直して「送る」と、カードが「送りました（田中）」になる。チャットを送ると偽物の返事が出る。コンソールにエラーがない

- [ ] **Step 5: Commit** — `git commit -m "feat(web): 会話・影響マップ・見張りと設定の画面を足す"`

---

### Task 7: インフラと配置（Container Apps、サインイン、ロール）

**Files:**
- Create: `web/Dockerfile`、`web/.dockerignore`（または `.dockerignore` をリポジトリ直下に）、`infra/modules/web.bicep`
- Modify: `infra/main.bicep`、`infra/modules/{identity,monitoring,webpubsub,foundry}.bicep`、`azure.yaml`

**Interfaces:**
- Produces: `main.bicep` の出力 `WEB_URL`、`WEB_APP_NAME`、`AZURE_CONTAINER_REGISTRY_ENDPOINT`
- Produces: Web の ID（ユーザー割り当て `id-web-<token>`）のロール: Cosmos の組み込み Data Contributor、プロジェクトの Foundry User、アカウントの Cognitive Services OpenAI User、Web PubSub Service Owner、レジストリの AcrPull

- [ ] **Step 1: Bicep を書く**
  - `identity.bicep`: 引数 `prefix`（既定 `func`）を足し、名前を `id-${prefix}-${resourceToken}` にする（Functions の ID の名前は変わらない）
  - `monitoring.bicep`: `logAnalyticsId` を出力する
  - `webpubsub.bicep`: `ownerPrincipalIds array` にし、所有者のロールを配列で付ける（ロールの割り当ての名前は今と同じ式で、Functions の分が作り直しにならないようにする）
  - `foundry.bicep`: 引数 `webPrincipalId` を足し、プロジェクトの Foundry User とアカウントの OpenAI User を付ける
  - `web.bicep`（`extension microsoftGraphV1`）:
    - レジストリ `cr${resourceToken}`（Basic、`adminUserEnabled: false`）と AcrPull（`7f951dda-4ed3-4680-a7ca-43fe172d538d`）
    - Container Apps の環境 `cae-${resourceToken}`（ログは `appLogsConfiguration.destination: 'azure-monitor'` にし、診断設定で Log Analytics に送る。共有キーを使わない）
    - サインイン用のアプリ登録（`signInAudience: 'AzureADMyOrg'`、`web.redirectUris: ['https://ca-web-${resourceToken}.${environment.properties.defaultDomain}/.auth/login/aad/callback']`、`web.implicitGrantSettings.enableIdTokenIssuance: true`）とそのサービスプリンシパル
    - アプリ `ca-web-${resourceToken}`（タグ `azd-service-name: web`、ユーザー割り当ての ID、外部からの受け口 8000、レジストリはマネージド ID で取得、最初のイメージは `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest`、`minReplicas: 0`、`maxReplicas: 1`、環境変数 `AZURE_CLIENT_ID`・`COSMOS_ENDPOINT`・`COSMOS_DATABASE`・`FOUNDRY_PROJECT_ENDPOINT`・`MEMORY_STORE_NAME`・`WEBPUBSUB_ENDPOINT`・`WEBPUBSUB_HUB`・`APPLICATIONINSIGHTS_CONNECTION_STRING`）
    - `authConfigs/current`: `platform.enabled: true`、`globalValidation.unauthenticatedClientAction: 'RedirectToLoginPage'`、`identityProviders.azureActiveDirectory.registration`（`clientId`、`openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'`。`clientSecretSettingName` は付けない）
  - `main.bicep`: Web の ID を作り、Cosmos の `dataContributorPrincipalIds`、Web PubSub、Foundry に渡す。`web` モジュールを足し、出力を足す

- [ ] **Step 2: Dockerfile と azure.yaml を書く**
  - Dockerfile: 1段目 `node:22.11.0-alpine` で `web/frontend` を `npm ci && npm run build`。2段目 `python:3.12-slim` に `ghcr.io/astral-sh/uv` のイメージから `uv` を入れ（版はローカルの `uv --version` と同じものに固定する）、リポジトリのワークスペース（`pyproject.toml`、`uv.lock`、`core/`、`functions/`、`web/`）を入れて `uv sync --frozen --no-dev --package proactive-web`。1段目の出力を `web/proactive_web/static/` に置く。起動は `uvicorn proactive_web.app:create_app --factory --host 0.0.0.0 --port 8000`
  - `azure.yaml` の `services.web`: `project: ./web`、`host: containerapp`、`language: python`、`docker: {path: ./Dockerfile, context: .., remoteBuild: true}`

- [ ] **Step 3: 確かめる**
  - Run: `az bicep build --file infra/main.bicep --stdout > /dev/null` / Expected: エラーも警告もない
  - Run: `docker build -f web/Dockerfile .`（Docker がなければ飛ばし、Task 9 のリモートビルドで確かめると記録する） / Expected: 成功
  - Run: `cd web && uv run pytest -q`、`cd functions && uv run pytest -q`、`cd deploy && uv run pytest -q`、`cd core && uv run pytest -q` / Expected: PASS

- [ ] **Step 4: Commit** — `git commit -m "feat(infra): Web アプリを Container Apps に置き、Entra のサインインとロールを付ける"`

---

### Task 8: シナリオテスト（設計書 9 節）

**Files:**
- Create: `web/proactive_web/scenario_checks.py`、`web/tests/test_scenario_checks.py`、`scripts/scenario_test.py`

**Interfaces:**
- Consumes: `ScenarioRunner`、`ChatService`、`build_state`、`visible_messages`、`analyze_impact`
- Produces: `scenario_checks.CheckContext(store: Store, memory: MemoryReader | None, before_ids: dict[str, set[str]])`（`before_ids` は手順の前にあった文書の ID。コンテナ名 → ID の集合）、`scenario_checks.Check(name: str, predicate: Callable[[CheckContext], bool], timeout_s: int)`、`scenario_checks.EXPECTATIONS: dict[str, list[Check]]`（キーは `"<シナリオ ID>#<手順の番号>"`）

- [ ] **Step 1: 失敗するテストを書く** — 期待値ごとに「満たす文書を入れると真、入れないと偽」を確かめる。少なくとも次を書く

```python
def test_s1_change_expects_code_determined_impact_set():
    ctx = ctx_with(notification(team="integrated_control", origin="SIG-BrkPedalPos", classification="notify_now",
                                impacted=analyze_impact(GRAPH, "SIG-BrkPedalPos").impacted_ids,
                                deliver_at="2026-11-18T08:00:00+09:00", delivered_at=None))
    assert passes(ctx, "s1_signal_period#0", "通知の影響範囲がコードの計算と一致する")
    ctx = ctx_with(notification(..., impacted=["MDL-MotorTq"]))  # 足りない
    assert not passes(ctx, "s1_signal_period#0", "通知の影響範囲がコードの計算と一致する")

def test_s1_night_expects_no_visible_message_for_tanaka(): ...
def test_s1_tanaka_reply_expects_escalation_to_chief(): ...
def test_s0_noise_expects_no_new_notification_or_message(): ...   # 調査の記録が done で、起点 SPEC-BRK-04 の silent 以外の通知がない
def test_message_mentions_ids_checks_text(): ...                   # 「SIG-BrkPedalPos」「MDL-MotorTq」を含むメッセージがあるか
```

- [ ] **Step 2: 失敗を確かめる** — Run: `cd web && uv run pytest -q tests/test_scenario_checks.py` / Expected: FAIL

- [ ] **Step 3: 実装する** — 期待値（文章の中身は判定しない。データ ID に触れているかだけ見る）:

| 手順 | 期待値（名前） | 上限 |
|---|---|---|
| s1#0 変更 | 統合制御の調査の記録が done／起点 SIG-BrkPedalPos、notify_now、届けるのは 11/18 08:00、未配達の通知が1件／通知の影響範囲がコードの計算と一致する／評価に analysis_request、評価から analysis_result が届く／モーター制御宛ての impact_notice の下書き（pending）がある／夜のあいだ田中の画面に新しいメッセージが出ない | 10 分 |
| s1#1 8:00 | s1 の通知が配達済み／田中の画面に提案つきのメッセージがあり、SIG-BrkPedalPos と MDL-MotorTq に触れている | 10 分 |
| s1#2 承認 | impact_notice が統合制御からモーター制御に届く／佐藤の画面にメッセージがあり、MDL-MotorTq に触れている | 8 分 |
| s1#3 佐藤 | モーター制御から統合制御へ human_reply（stance cannot、本文は佐藤の発言そのもの）／佐藤へのチャットの返事がある | 6 分 |
| s1#4 田中 | 統括に escalation が届く／高橋の画面に notify_now の通知にひもづくメッセージがあり、MDL-MotorTq に触れている | 10 分 |
| s5#0 | 統合制御に test_failure_streak（regen_coord、すぐ）の見張りがある | 5 分 |
| s5#1 | 統合制御の Memory の項目が1つ以上増える | 5 分 |
| s5#2 | s5#1 で増えた項目がなくなる | 5 分 |
| s2#2 3回目の失敗 | 統合制御の調査の記録が done／統合制御に notify_now の通知があり、配達済み（16:00 は静かな時間帯の外） | 10 分 |
| s0#0 誤字の修正 | 統合制御の調査の記録が done／起点 SPEC-BRK-04 の silent 以外の通知がなく、田中の画面に新しいメッセージがない | 8 分 |
| s3#0 11/19 8:00 | 4体の `run-morning-<チーム>-20261119` が done | 15 分 |
| s4#0 11/23 8:00 | `sch-release-gap-R3` が実行済み／統括に R3 に触れたメッセージがある | 10 分 |

  - `scripts/scenario_test.py`: シードを作り直し、`ScenarioRunner` で手順を順に進める。`StepNotReady` なら `sync` を呼びながら5秒ごとに5分までやり直す。手順のあと、期待値を5秒ごとに読み直して上限まで待つ（待つあいだも `sync` を呼ぶ）。満たせなくても次の手順に進み、最後に OK / NG の一覧と件数を出し、NG があれば終了コード 1。追加で2つ確かめる:
    - **二重通知がない**: s1#0 の期待値が揃ったあと、`ce-s1-1` をもう一度 `upsert` して 90 秒待ち、統合制御の調査依頼と通知の数が変わらない
    - **朝のまとめが1回だけ**: s3#0 のあと、4体の Routines を `FoundryRoutineDispatcher` でもう一度起動し、2 分待っても `run-morning-*` と朝のメッセージの数が変わらない
  - 使い方の説明に「Azure 上のデモのデータを消して作り直す。モデルの呼び出しの費用がかかる（全体で 40 分ほど）。終わったあとはデータを残すので、画面で結果を見られる」と書く

- [ ] **Step 4: 通ることを確かめる** — Run: `cd web && uv run pytest -q` / Expected: PASS

- [ ] **Step 5: Commit** — `git commit -m "test: 5つのシナリオを本物の LLM で通すシナリオテストを足す"`

---

### Task 9: Azure 上での確認と README

**Files:**
- Modify: `README.md`、本書の末尾（「実装時の決定」）

- [ ] **Step 1: 制作者に確認してから `azd up`** — `proactive-dev` に反映する（デモのデータが作り直され、モデルの費用が少しかかる）。Expected: 成功。初回は Web の ID のロールが効くまで BFF が 403 を返すことがある。数分待っても続くなら原因を調べる
- [ ] **Step 2: 画面を確かめる** — `WEB_URL` をブラウザで開き、制作者の Entra アカウントでサインインする（サインインは制作者が行う）。人物の切り替え、マップ、デモの操作の手順の一覧が出ることを確かめる。サインインしていない別のブラウザからは、サインインの画面に飛ばされることを確かめる
- [ ] **Step 3: 既存のスモークテスト** — Run: `uv run --package proactive-functions python scripts/smoke.py` / Expected: `SMOKE OK`
- [ ] **Step 4: シナリオテスト** — Run: `uv run --package proactive-web python scripts/scenario_test.py` / Expected: すべて OK。NG があれば、エージェントの指示文の問題か、コードの問題かを切り分ける。コードは TDD で直し、指示文は直してフックを流し直す。それでも LLM の判断で揺れるものは、何回に何回通ったかを記録する。s1#3 の human_reply が書けないときは、まず MCP サーバーの拒否「人の返事の本文は、元の発言と同じでなければなりません」を疑う（エージェントが句読点や空白を変えた。ゲートウェイの検査は緩めず、指示文で直す）
- [ ] **Step 5: 画面でシナリオ1を通して見る** — デモの操作で最初からやり直し、「次へ」でシナリオ1を進め、田中・佐藤・高橋の画面の見え方を確かめる（グラフの表示を含む）
- [ ] **Step 6: README を直す**
  - 「状態」を「Plan 4 まで実装済み」に
  - 画面の使い方（サインイン、人物の切り替え、3区画、承認カード、デモの操作）
  - シナリオの進め方（画面と `scripts/scenario.py`）とシナリオテストの流し方、かかる時間と費用
  - 構成図に Web アプリを足す。サインインがクライアントシークレットなしの暗黙的フロー（ID トークンだけ）である理由（キーを持たない方針）と、Microsoft が暗黙的フローを勧めていないこと
  - 費用: Container Apps はゼロまで縮む。コンテナーレジストリ（Basic）は使わなくても月に数百円かかる
  - 事前の承認（決定 8）
- [ ] **Step 7: 実装時の決定を本書の末尾に書く**（Plan 3 と同じ形式。実装中に決めたこと、シナリオテストの結果、残った課題）
- [ ] **Step 8: Commit** — `git commit -m "docs: Plan 4 の画面とシナリオの使い方を README に書き、実装時の決定を追記"`

## 実装時の決定

### 実装中に決めたこと

- **アプリの作り方**: `create_app` に `static_dir` を、`Deps` に `auth_mode` を足した（画面の配信とサインインの有無をテストで切り替えるため）。画面のファイルは BFF の利用者の確認なしで返す（組み込み認証がアプリ全体を守る）。`/api/*` は必ず確認する
- **エージェントの指示文のテスト**: `source_message_id` を、道具の名前ではない語の一覧に足した（`send_mail` の引数名で、チャットの節が名前を挙げる）
- **影響マップの大きさ**: 列の幅 118px、ノードの幅 100px（1440px の画面で6列が中央に収まる）。領域のラベルに「・準備中」を付ける
- **Web のインフラ**: BFF に Application Insights の接続文字列は渡さない（BFF に SDK がなく、Application Insights はローカル認証を無効にしている）。コンテナーのログは Log Analytics に入る。ACR の名前の長さの検査のため `resourceToken` に `@minLength(13)` を付けた
- **シナリオテストの期待値**: s5#1、#2 の記憶は「朝」の語で判定する（手順をまたいで項目の ID を持たない）。「起きないこと」の期待値には `final` を付け、ほかの期待値が揃ってから1回だけ判定する

### 最終レビューで直したこと

- **承認の順番**（決定 7 を変更）: 提案を先に etag 付きで `pending → approved` に書き換えて確保し、そのあとでメールを書く。メールを先に書くと、却下と同時に押されたとき、却下された提案のメールが届いてしまう。確保したあとメールを書く途中で止まった分は、同じチームがもう一度承認を押せば、保存した本文で揃う（2回目の承認は 409 ではなく、そのまま成功）。却下できるのは `pending` のときだけ
- **チャットの確保**（決定 6 に追加）: 送る処理のあいだ `system/chat-claim-<チーム>` を新規作成して確保し、同時に送られた2つ目を 409 にする。送り終えたら消す。送る途中で止まって残った確保は、2分（実時間）を過ぎたら無視する
- **チャットの待ち時間**（決定 4 を変更）: 10 分は実時間で測る（`detail.started_real_at`）。シナリオの手順が仮想の時計だけを大きく進めると、書いている途中の返事が timeout で閉じられていた
- **時計の手順の前提**（決定 17 を変更）: 「pending の依頼がない」だけでは、変更フィードのトリガーが依頼を作る前と、起動の印を付けてから作業記録ができるまでの隙間を通ってしまう。直前の時計の手順より後に流した変更・試験結果と、すべてのエージェント間メールから、Functions と同じ振り分け（`vehicle_core.routing`、`handlers.mail_request`）で依頼の ID を求め、依頼がない／pending／dispatched なのに `run-inv-<ID>` が done でない、のどれかなら待つ。まとめられた依頼は `merged_into` をたどる。起動の印を付けたまま 15 分（仮想の時刻）たっても作業記録ができない依頼は、止まったものとみなす
- **承認の手順**（決定 18 に追加）: 承認待ちがなくても、画面で先に承認した `impact_notice` があれば、その提案で足りないメールを揃えて済ませる
- **「次へ」の前の返事の受け取り**: 画面を開いていないチームの返事は誰も受け取らないので、`/api/admin/next` の最初に全チームの `sync` を呼ぶ
- **サインインの割り当て**: サインイン用のサービス プリンシパルに `appRoleAssignmentRequired` を付け、デプロイした人（`principalId`）を既定の役割で割り当てる。デモのデータを作り直す操作をテナントの全員に開かないため。`principalId` が空のときは割り当てを求めない（誰もサインインできなくなるのを避ける）
- **シナリオテストの待ち時間**: 「次へ」が前提を待つ上限を 600 秒にした（時計の手順が、メールから起きる調査まで待つようになったため）

### 最終レビューで直さなかったこと（小さな指摘）

- 記憶の判定は「朝」の語で行うので、s5#0 の文（「朝を待たずに」）がそのまま記憶されると s5#2 が NG になる。シードの作り直しは Foundry Memory を消さないので、2回目のシナリオテストでは s5#1 が初めから OK になる
- `run-morning-…` は `response_id` を持たないので、`reconcile_runs` が閉じない。Routine が `finish_run` を呼ばずに止まると、時計の手順が s4 の前で待ち続ける
- `/api/admin/clock` は調査の前提を確かめず、時計を戻すこともできる
- 例外の扱い: `admin_next` は `ChatFailed` と `ValueError` を日本語の理由に直さない。`/api/files` は Foundry のエラーを 500 のまま返す。`ChatService.send` は、作業記録の作成に失敗すると応答が宙に浮く
- 「次へ」の進み具合の書き込みが、手順を行ったあとで別の操作と重なると、あとで同じ手順をもう一度行う（2つのタブから同時に押すと人の発言が2回送られる）。発表者が手で打った発言も、人の発言の手順でもう一度送られる
- 変更の手順は `change_events` を先に書くので、トリガーが変更前のデータを読むことがある。データの書き換えが3回とも失敗したときは黙って飛ばす
- `/api/state` の `proposals` に、まだ配達されていないメッセージの提案も入る（画面には出ないが、通信には含まれる）
- 画面: 前の人物への遅い応答が、切り替えた後の画面を上書きすることがある。組み込み認証のセッションが切れると、読み直しが分かりにくい形で失敗する（サインインの画面に飛ばさない）。承認カードのバッジは、承認後も「承認待ちの下書き」のまま。読み直しのたびに Foundry Memory を検索する
- Dockerfile は root で動き、ベースイメージをダイジェストではなくタグで指定している
- s1 のエスカレーションは、LLM が佐藤の発言を一字一句写すことに依っている（ゲートウェイがメールの本文と元の発言を比べる）

### 判断を保留した点の扱い

- 統括の画面に出す提案・メッセージ・見張りは、統括自身のものだけ（決定 10 のまま）。設計書 7.5 節の表では全チームの提案を見られる。どのシナリオでも統括が他チームの下書きを承認しないため、変えていない
- 「完了」の欄は、配達前の夜の作業記録も `detail.summary` つきで出す。完了の欄は作業の記録で、知らせではない（夜に会話へ書き込んだり、バッジを付けたりはしない）

### Azure 上での確認（1回目）

`azd up` のあと、スモークテストとシナリオテストを Azure 上で通した。

- スモークテスト: 朝のまとめの確認だけが NG。ほかは OK
- シナリオテスト: OK 16 / NG 10。NG は次の4つの原因に分かれた

1. **メールが届かない**（s1#0 の analysis_result、s1#2〜#4、s3・s4 が調査待ちで止まる）。Functions の `deliver_agent_mail` が、デプロイしてから一度も動いていなかった。`agent_mail` と `watches` の変更フィードのリースには、続きの位置（チェックポイント）が一度も書かれていない。続きの位置がないと、新しく起動したインスタンスはそのたびに「いま」から読み始めるので、起動のきっかけになった文書を読み飛ばしていた（Flex Consumption はトリガーごとにインスタンスを起動する）。すべての Cosmos トリガーに `start_from_beginning=True` を付けた。続きの位置が書かれたあとは効かない。処理はどれも冪等で、シードの文書は読み飛ばすので、最初から読み直しても害はない
2. **朝の起動が抜ける**（スモークテスト）。時計を 8:00 に合わせると、その 0.1 秒後に動いた tick には 7:59:59.6 に見えた。合わせた PC の時計が Azure より 0.5 秒ほど進んでいたためである。この tick は朝を越えていないと判定したうえで、判定の基準（`last_tick`）だけを書き換えた。そのため、0.3 秒後の tick が通知を配達しても、朝の起動はもう起きなかった。時計の文書に合わせた時刻（`virtual_at`）を持たせ、読む時刻をそれより前にしないようにした。シナリオテストでは tick が遅れて動いたので起動できていた
3. **見張りが鳴らない形で登録された**（s5#0）。エージェントが feature に「回生協調」と書いた。試験結果の feature は `regen_coord` で、見張りとは完全一致で比べるので、この見張りは鳴らない。`add_watch` は、試験ケースにない feature を、正しい値の一覧を付けたエラーで断る。道具の説明にも例を書いた
4. **誤字の修正を知らせた**（s0）、**評価に解析を頼まない**（s1#0 の analysis_request）。調査の依頼の文に、変更の前と後の値がなかった。エージェントは、何が変わったかを知らないまま `trace_impact` の影響範囲だけで判断していた。依頼の文に「変更の中身」（項目、前、後、題名や説明文だけの変更か）を入れた。スキルには次のことを足した
   - notify-decision: 意味の変わらない修正は silent
   - investigate: 周期や定数のような数値の変更は、評価に `analysis_request` を送る。silent にした変更では下書きを作らない

s1#3（佐藤の発言の human_reply）は、モーター制御が影響の連絡のメールを受け取れていなかったので、ほかの NG が直ってから見直す。

### Azure 上での確認（2回目）

1回目の直しを `azd up` で配置して、もう一度通した。

- スモークテスト: すべて OK
- シナリオテスト: OK 24 / NG 4。1回目の NG のうち、メール、朝の起動、見張りの登録、誤字の修正、s3・s4 は直った。残りの NG は次の3つの原因に分かれた

1. **見張りが鳴らない**（s2#2）。シナリオは時計を進めながら試験結果を3件続けて入れるので、変更フィードは3件をまとめて届ける。1件目を判定するとき、Store にはもう2件目と3件目があり、「より新しい結果があるのに遅れて届いた古い結果」とみなされて見張りが鳴らなかった。3件目では連続失敗が3回になり、エージェントが登録した streak=1 とちょうど一致しない。試験結果のハンドラーは、履歴をその結果より前に実行されたものだけにした。まとめて届いても、別々に届いても同じ判定になる。遅れて届いた古い結果は、もう一度鳴ることがある
2. **人の返答が他チームに届かない**（s1#3 の human_reply、s1#4 の escalation）。どのチームも `send_mail` を一度も呼んでいなかった。道具は許可されている。チャットの会話は調査の会話と別なので、佐藤が「対応は無理です」と書いても、エージェントはそれがどの影響の連絡への返答かを知らなかった（`list_mail` も呼んでいない）。チャットのプロンプトに、そのチームが関わる影響の連絡、人の返答、エスカレーションのメール（新しい順に5件まで、thread_id、送り手と宛先、stance、関係するデータ）を添えた。s1#4 は s1#3 の返答が届いてから起きるので、同じ原因である
3. **評価に解析を頼まない**（s1#0）。スキルの手順5に書いても、エージェントは手順を飛ばした。調査の依頼の文で、数値の変更（前と後がどちらも数）のときは手順5を指す一行を足した。評価チーム自身の調査には足さない。あわせて、メールが起点の調査の依頼の文に、メールの中身（種類、送り手、thread、stance、本文）を入れた。届いた依頼や返答を、`list_mail` を呼ばなくても読める

### Azure 上での確認（3回目）

2回目の直しを `azd deploy` で配置して、もう一度通した。

- スモークテスト: すべて OK
- シナリオテスト: OK 25 / NG 3。2回目の NG（見張り、human_reply、escalation、analysis_request）はすべて直った。評価への解析の依頼が通ったことで、夜のあいだに「依頼 → 評価の解析 → 結果 → 統合制御の2つ目の調査」が走るようになり、次の3つが出た

1. **夜に田中の画面にメッセージが出た**（s1#0）。統合制御の調査が、通知を記録したあと、notification_id を付けずに `post_message` した。スキルには「必ず渡す」と書いてある。`post_message` は、notification_id が渡されないとき、そのチームが 30 分以内に記録してまだ届けていない notify_now の通知に結びつける。静かな時間帯のメッセージは、通知と一緒に翌朝届く。digest には結びつけない（朝のまとめのメッセージまで翌日に回してしまうため）
2. **同じ変更イベントを2回流すと通知が増えた**（シナリオテストの追加の確認）。増えた通知は、解析の結果を受けた統合制御の2つ目の調査が silent で記録したもので、もう一度流した変更イベントからは何も起きていない。確かめ方の誤りなので、連鎖が落ち着くまで待ってから数えるようにした
3. **朝の提案つきメッセージに MDL-MotorTq がない**（s1#1）。本文が「motor_control への影響下書き」とチーム名だけだった。investigate スキルの手順8に、下書きと結びつけるメッセージには起点と相手チームの影響を受けるデータの ID を書くことを足した。あわせて、エージェントが自チームあての impact_notice の下書きを作っていたので、`create_proposal` は自チームあてを断る

### Azure 上での確認（4回目）

3回目の直しを `azd deploy` で配置し、`azd hooks run postdeploy` でスキルとエージェントを更新して（v8）、もう一度通した。

- スモークテスト: すべて OK
- シナリオテスト: s1#0 で NG。評価への解析の依頼と結果（83 秒）、夜のあいだ田中の画面に出ないこと、重複の確認は OK になった。ただし、モーター制御あての下書きができず、その先の手順が「承認待ちの影響の連絡がまだありません」で進めなくなった。s0 の途中で手元の DNS が一時的に引けなくなり、シナリオテストが例外で止まった（Azure 側の問題ではない）

1. **下書きができなかった**（s1#0）。統合制御の1つ目の調査は、`send_mail`（analysis_request）と `record_notification` まで呼んで、`create_proposal` も `finish_run` も呼ばずに応答を終えた（作業記録は tick が閉じた）。解析の結果を受けた2つ目の調査は「同じ件はもう知らせた」として silent で終え、下書きを作らなかった。数値の変更を指す1行に「結果は待たずに、この調査で通知の記録と下書きまで進める」を足した。解析の結果を受けた調査には、起点についての自チームの下書き（却下を除く）を書く。まだなければ「この調査で create_proposal で作る」、あれば「同じ件の下書きは新しく作らない」

### Azure 上での確認（5回目）

4回目の直しを `azd deploy functions` で配置して、もう一度通した。

- スモークテスト: すべて OK
- シナリオテスト: OK 23 / NG 5。初めて最後（s3 の朝のまとめ、s4 のリリースの抜け）まで通った。4回目の NG（下書きができない）は直った。NG 5 件の原因は3つで、2件はその先の手順に波及したもの。3回目に OK だった escalation と見張りが、今回は NG になった（エージェントの振る舞いの揺れ）

1. **朝の提案つきメッセージに MDL-MotorTq がない**（s1#1）。本文に起点と自チームの影響（MDL-RegenCoord、TC-HILS-031〜035）は書いたが、モーター制御で影響を受けるデータを書かなかった。指示文の影響の要約はチームごとの件数だけだったので、相手チームで影響を受けるデータの ID（チームごとに10件まで）を並べる
2. **田中が譲らないと言っても escalation が出ない**（s1#4。高橋の画面の NG はこの波及）。チャットの指示文には、佐藤の human_reply（stance cannot）のスレッドが載っていた。それでもエージェントは、統括への escalation でなく、同じ件の impact_notice の下書きをもう1つ作った。相手からこのチームあてに stance cannot の human_reply が届いているとき、チャットの指示文に「譲れないという意味なら、その thread_id で chief_engineer に escalation を送る。同じ件の下書きは新しく作らない」を足す
3. **見張りの機能を取り違えた**（s5#0。s2#2 の通知の NG はこの波及）。「回生協調」の依頼で、feature を motor_torque にした。値としては正しいので `add_watch` は断れない。`add_watch` は、見張る試験ケースの ID と題名（「TC-HILS-012: モータートルク応答 HILS 試験」）を返し、依頼と違えば消して足し直すよう添える。知らない値を断るときの一覧にも、値ごとの試験ケースの題名を添える

### Azure 上での確認（6回目）

5回目の直しを `azd deploy`（Functions と Web）で配置して、もう一度通した。

- スモークテスト: すべて OK
- シナリオテスト: OK 26 / NG 2。5回目の NG（朝のメッセージの MDL-MotorTq、escalation、見張り、HILS の即時の通知）はすべて直った。残りの2つは、エージェントの揺れではなく道具の作りの問題だった

1. **佐藤へのチャットの返事が出ない**（s1#3）。佐藤のアシスタントは human_reply を送ったあと、チャットの作業記録（run-chat-…）を `finish_run` で閉じた。画面は running の記録だけを読み直して返事を書き写すので、返事が会話欄に出なかった。`finish_run` はチャットの作業記録を断る
2. **高橋の画面で、判断が要るメッセージが通知に結びつかない**（s1#4）。統括のアシスタントは escalation を受けて notify_now を記録し、すぐ notification_id なしで `post_message` した。3回目に入れた結びつけは、翌朝まで保留する通知だけが対象だった。昼にすぐ届けた notify_now も、記録から5分以内のメッセージなら結びつける

### 画面での確認（シナリオ1）

6回目の直しを `azd deploy functions` で配置し、`scenario.py reset` でデータを作り直してから、画面の「次へ」でシナリオを進めた。手順はエージェントの連鎖が落ち着く前に進めたので、時刻はずれている。

- 佐藤へのチャットの返事が出た。高橋の判断が要るメッセージは notify_now の通知に結びつき、先頭に並んだ。escalation、回生協調の見張り（regen_coord）、HILS の即時の通知、SPEC-BRK-04 の誤字の修正を知らせないことも、データの上で確かめた
- 田中の会話欄には、提案つきのメッセージが出なかった（下書きはあり、承認で佐藤に届いた）。エージェントの揺れとして記録する
- **評価チームの解析が止まった**。評価のアシスタントの応答が、`get_test_log` を呼んだあと Foundry で in_progress のまま2時間終わらなかった。tick は毎分状態を調べるが、終わった応答しか閉じないので、作業記録が running のまま残り、時計を進める手順が「調査が終わっていません」で止まり続けた。止まった記録は手で時間切れとして閉じた。調査の作業記録に実時間の開始時刻を書き、実時間で30分を過ぎても in_progress / queued の応答は、取り消しを試みてから時間切れ（error: timeout）として閉じる
