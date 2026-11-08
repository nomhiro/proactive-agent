# Plan 3: Foundry のエージェント（harness 付きプロンプトエージェントと MCP サーバー） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `azd up` 1回で、Copilot harness を使うプロンプトエージェント4体が Foundry にでき、Functions 上の MCP サーバーだけを通して Cosmos DB を読み書きし、変更フィードと Routines から起動されて、調査の結果（通知、メッセージ、提案、作業記録）を残す状態にする。

**Architecture:** Plan 2 の Functions に MCP サーバー（`/api/mcp`、JSON-RPC over Streamable HTTP、JSON 応答のみ）を足し、HTTP の書き込み窓口を置き換える。道具は `proactive_functions/mcp/` に置き、呼び出し元のチームはトークンの `azp` と `team_settings.agent_client_id` の対応表で決める。エージェントの指示文とスキルは `agents/` に置き、新しいワークスペースのメンバー `deploy/`（`proactive_deploy`）が、azd のフックで MCP 接続、エージェント、ロール、対応表、Routines を作る。

**Tech Stack:** Python 3.12、Azure Functions（Flex Consumption、Python v2）、azure-ai-projects 2.10 以降、azure-mgmt-authorization、azure-storage-blob、azure-cosmos、azure-identity、PyJWT[crypto]、Bicep、azd 1.37 以降（`azure.ai.agents` 拡張 1.0.0-beta.22 以降）、pytest

**Spec:** `docs/superpowers/specs/2026-11-07-proactive-vehicle-agent-design.md` 第2版（特に 4.2〜4.3、6、7.3〜7.11、9、12 節）。経緯: `docs/superpowers/specs/2026-11-08-foundry-rearchitecture-proposal.md` 9.1 節。前提: Plan 2（`docs/superpowers/plans/2026-11-08-plan2-infra-functions.md` の末尾「実装時の決定」を含む）

### 計画全体の中での位置づけ
| 計画 | 中身 |
|---|---|
| Plan 1（済） | `vehicle_core`: 判定ロジックと架空データ |
| Plan 2（PR #2） | azd + Bicep の基盤、Functions（振り分け、まとめ、定時実行、メール配達、画面への通知） |
| **Plan 3（本書）** | 残りの確認、MCP サーバー、本物の `AgentInvoker`、エージェント4体、Routines、デプロイのフック |
| Plan 4 | Web アプリ（BFF と画面、チャット、グラフの表示）、シナリオを進める仕組み、シナリオテスト |

### 始める前に
- ブランチ: PR #2 がマージ済みなら `main` から `feat/plan3-foundry-agents` を切る。未マージなら `feat/plan2-infra-functions` から切る。どちらの場合も、続けて `docs/spec-foundry-harness`（設計書第2版と spike を含む）をマージする
- 確認用の環境 `proactive-spike`（`spikes/harness/`）は Task 1 で使う。Task 1 が終わったら、制作者に確認してから `azd down --purge` で消す

## Global Constraints

- Python は 3.12（`requires-python = ">=3.12"`）
- 地域は `japaneast`（設計書 6.3 節）
- キーと接続文字列を使わない（設計書 10 節）。Foundry のアカウントは `disableLocalAuth: true`。HTTP 関数は `AuthLevel.ANONYMOUS` にし、コードで Entra のトークンを検証する
- エージェントの ID には Cosmos DB のロールを一切付けない（設計書 7.5 節）。Plan 2 の申し送りにあった「エージェントに Data Reader を付ける」は行わない
- 関数ツールは使わない。エージェントの道具は MCP サーバーの道具だけ（設計書 7.11 節 1）
- エージェントへの要求に `temperature`、`max_output_tokens`、`truncation`、`store`、`previous_response_id` を入れない（設計書 7.11 節 5）
- 調査1件に会話1本（設計書 7.11 節 4）
- Functions と MCP サーバーの中の現在時刻は、必ず仮想時計（`StoredClock`）から取る。`datetime.now()` を直接呼ばない（Plan 2 から継続）
- 書き込みは `vehicle_core.gateway.authorize_agent_write` を必ず通し、返ったモデルを保存する（Plan 2 から継続）
- 道具の説明、拒否の理由、画面に出る文字列、指示文とスキルは日本語
- エージェント名は `asst-` + チームの値の `_` を `-` にしたもの（例: `asst-integrated-control`）
- `azd provision`・`azd up`・`azd down` と Azure 上のデータを消す操作は、実行の前に制作者に確認する
- 登場するデータはすべて架空

### 設計書の隙間を埋めた決定（実装者はこのとおりに作る）
1. **MCP の受け口**: Functions の HTTP 関数 `POST /api/mcp`。spike の `spike_mcp.py` と同じく、状態を持たない JSON-RPC を JSON で返す（SSE は使わない）。`GET` などは 405。対応する MCP のプロトコル版は `2025-06-18` と `2025-03-26`、それ以外を求められたら `2025-06-18` を返す
2. **認証の順序**: 本文を読む前にトークンを検証する。トークンがない・不正なら HTTP 401、対応表にない `azp` なら HTTP 403。どちらも道具は1つも動かさない。`initialize` と `tools/list` にもトークンを求める
3. **トークンの宛先**: Plan 2 の書き込み窓口用アプリ登録（`gateway-app.bicep`、出力 `GATEWAY_APP_ID` / `GATEWAY_APP_ID_URI`）を、そのまま MCP サーバーの宛先に使う。名前は変えない（アプリ登録を作り直さないため）。`GATEWAY_AUDIENCES` には app ID と URI の両方を入れる（spike で `aud` は app ID の GUID だった）
4. **HTTP の書き込み窓口を外す**: `agent/{container}/{item_id?}` のルートと `gateway_http.py` を消す。保存の処理（新規作成、作業記録の置き換え、見張りの削除、通知の配達時刻の決め直し）は `proactive_functions/agent_writes.py` に移し、MCP の書き込みの道具から呼ぶ
5. **道具の引数で決めさせないもの**: `id`、`team`、`vehicle_id`、`created_at`、`author`、`role` はサーバーが決める。エージェントが渡しても無視する。ID は `<接頭辞>-<uuid4 の先頭12文字>`（例: `msg-1a2b3c4d5e6f`）
6. **通知の根拠はコードで求める**: `record_notification` に `origin_artifact_id` があれば、`impacted_ids`・`highlight_ids`・`cross_team_edges` はサーバーが `analyze_impact` で求める（エージェントの値は使わない）。起点がない通知（HILS の失敗傾向など）は、エージェントが渡した `impacted_ids` のうち `artifacts` にあるものだけを残し、`highlight_ids` も同じ値、`cross_team_edges` は空にする
7. **道具の失敗の返し方**: 道具の中の拒否や入力の誤りは、JSON-RPC のエラーではなく、`tools/call` の結果に `isError: true` と日本語の理由を入れて返す（LLM が読んで直せるように）。未知のメソッド・未知の道具・JSON でない本文は JSON-RPC のエラー（`-32601`、`-32602`、`-32700`）で返す。どの場合も HTTP 500 にしない
8. **読み取りの範囲**: 設計書 7.5 節の表をコードの1か所（`mcp/scope.py`）に置く。一覧の道具の `team` 引数は統括だけが使え、ほかのチームが渡したら自チームに置き換える
9. **朝のまとめの1日1回**: 道具 `begin_morning_digest` が `agent_runs` に ID `run-morning-<チーム>-<仮想の日付 YYYYMMDD>` を新規作成する。作れたら `{"already_done": false, "run_id": …}`、409 なら `{"already_done": true}`。Routines の指示文は最初にこれを呼び、`already_done` なら何もせず終える
10. **調査の起動**: `FoundryInvoker.invoke` は、会話を作り、`background=True` で Responses を送り、受け付けられたら戻る。続けて `investigations` の記録に `conversation_id` と `response_id` を書き、`agent_runs` に `run-inv-<依頼 ID>`（`state: "running"`）を作る。指示文に `run_id` を入れ、エージェントは調査の最後に `finish_run` で同じ記録を `done` にする
11. **終わらなかった調査**: tick が、`running` のまま `started_at` から 2 分を過ぎ `detail.response_id` を持つ作業記録の応答の状態を調べる。`failed`・`cancelled`・`incomplete` なら `done` にして `detail.error` に状態を書く。`completed` なのに `running` のままなら `done` にして `detail.closed_by = "tick"` を書く。`in_progress` と `queued` はそのまま
12. **HILS ログ**: `vehicle_core.hils_logs.render_hils_log(run)` が、試験結果から決まった CSV（同じ入力なら同じ出力）を作る。シードの投入で、シナリオに出てくる試験結果すべての `log_blob` に、このログを置く。`get_test_log` は 200,000 文字で切り、`truncated` を返す
13. **記憶の置き場所**: `MemoryBackend` の境目を作り、Task 1 の確認 5 の結果で実装を1つ選ぶ（成り立てば Foundry の Memory ストア、成り立たなければ Cosmos の `team_memory` コンテナ）。scope はチームの値
14. **グラフ**: Task 1 の確認 4 が成り立てば、エージェントは Foundry Files のファイル ID を `post_message` の `attachments` に `foundry-file:<ID>` として入れる。成り立たなければ、道具 `save_chart_data` を足し、グラフの数値（題名、軸の名前、系列ごとの点の列）を Blob の `analysis-artifacts/chart-<uuid4 の先頭12文字>.json` に置いて、その参照 `blob:analysis-artifacts/chart-<…>.json` を返す。エージェントはそれを `post_message` の `attachments` に入れる。道具は Task 5 に足し、Functions の ID に `analysis-artifacts` への書き込み権限を付ける
15. **尋ねる手段**: Task 1 の確認 8 が成り立てば、統括に A2A の道具（相手は3体）を付ける。成り立たなければ付けない（`send_mail` の `question` / `answer` で尋ねる）
16. **Routines**: Task 1 の確認 7 が成り立てば、朝のまとめとブリーフィングの `schedules`（`sch-digest-*`、`sch-briefing-*`）をシードから外し、Routines を作る。成り立たなければ `schedules` を残し、Routines は作らない（Task 2 と Task 10 の該当の手順を飛ばす）

## Review Focus

1. **対応表にない ID からの MCP 呼び出し**（作り直す前の古いエージェント、テナント内のほかのアプリ）→ HTTP 403 で、道具は1つも動かない。テストは Task 3 に入れる
2. **エージェントが引数で別のチームを名乗る**（`team`、`id`、`scope` を渡す）→ 無視され、呼び出し元のチームとして扱われる。テストは Task 4、5、6 に入れる
3. **朝のまとめが実時間の Routines と手動起動で二度動く** → 2回目は `already_done: true`。テストは Task 4 に入れる
4. **壊れた入力**（JSON でない本文、未知の道具、型の違う引数、必須の引数がない）→ JSON-RPC のエラーか `isError: true` で返り、HTTP 500 にならない。テストは Task 3 と Task 4 に入れる
5. **HILS ログがない**（`log_blob` が空、Blob に存在しない）→ `isError: true` で「ログがありません」を返し、例外にしない。テストは Task 5 に入れる

---

## ファイル構成

```
pyproject.toml                          # members = ["core", "functions", "deploy"]
azure.yaml                              # postdeploy フックを足す
core/src/vehicle_core/
  constants.py                          # agent_name() を足す
  hils_logs.py                          # 新規: render_hils_log、scenario_log_blobs
  clock.py                              # crossed_morning() を足す
  seed.py                               # build_schedules から朝の仕事を外す（決定16）
functions/proactive_functions/
  agent_writes.py                       # gateway_http.py から移した保存の処理
  foundry_invoker.py                    # 新規: FoundryInvoker、reconcile_runs
  prompts.py                            # 新規: investigation_prompt
  settings.py                           # Foundry、記憶、Blob の設定を足す
  seeding.py                            # HILS ログの投入を足す
  tick.py                               # reconcile_runs を呼ぶ
  mcp/
    __init__.py
    protocol.py                         # JSON-RPC、道具の登録簿
    context.py                          # ToolContext、ToolError
    scope.py                            # 読み取りの範囲（設計書 7.5 節の表）
    read_tools.py
    write_tools.py
    memory.py                           # MemoryBackend と記憶の道具
    server.py                           # build_registry、handle_mcp_http
functions/function_app.py               # mcp ルートを足し、agent ルートを消す
agents/
  instructions/<チーム>.md              # 4体の指示文
  skills/investigate/SKILL.md
  skills/notify-decision/SKILL.md
  skills/analysis/SKILL.md
  skills/analysis/regen_model.py        # 回生協調の簡易モデル
  skills/drafting/SKILL.md
  routines.md                           # Routines の指示文（統括とチームの2種類）
deploy/
  pyproject.toml                        # name = "proactive-deploy"
  proactive_deploy/
    definitions.py                      # エージェント、ロール、Routines の定義（純粋な関数）
    roles.py                            # ロールの割り当て（冪等）
    setup.py                            # postdeploy フックの本体
  tests/
infra/modules/foundry.bicep             # 新規
infra/main.bicep                        # foundry を足し、出力を足す
infra/modules/functions.bicep           # アプリ設定を足す
scripts/clock.py                        # 朝 8:00 を越えたら Routines を手動起動
scripts/smoke.py                        # Plan 3 の確認を足す
```

---

### Task 1: 残りの確認（spike 4、5、7、8 と、azd でのエージェント定義）

設計書 12 節の6項目を確かめ、決定 13〜16 のどちらで作るかを決める。確認なので単体テストの RED-GREEN はない。スクリプトは spike と同じく `spikes/harness/scripts/` に置き、結果は `results/` に JSON で残す（コミットしない）。API の形は、着手時に microsoft-docs のスキルで Microsoft Learn の最新の記載を引いてから書く。

**Files:**
- Create: `spikes/harness/scripts/probe_files.py`、`probe_memory.py`、`probe_routines.py`、`probe_a2a.py`、`spikes/harness/agents/`（azd の定義を試すもの）
- Modify: `spikes/harness/infra/modules/foundry.bicep`（記憶に要るモデルを足す）、`spikes/harness/README.md`、`docs/superpowers/specs/2026-11-08-foundry-rearchitecture-proposal.md`（9.1 節）、`docs/superpowers/specs/2026-11-07-proactive-vehicle-agent-design.md`（12 節と、切り替えた場合は該当の節）

**Interfaces:**
- Produces: 再検討案 9.1 節の表に、4、5、7、8 と「azd での定義」「スキルの添付」「RAI ポリシーの Network ルール」の結果を書き足す。最後に次の表を置き、Task 2 以降はこれを見て分岐する

| 決定 | 結果 |
|---|---|
| 13 記憶 | `foundry` か `cosmos` |
| 14 グラフ | `foundry-files` か `chart-data` |
| 15 尋ねる | `a2a` か `mail` |
| 16 Routines | `routines` か `schedules` |
| エージェントの定義 | `azd` か `sdk`（`azd` の場合は agent.yaml の雛形を `spikes/harness/agents/` に残す） |
| スキルの添付 | 登録と添付に使う API（またはポータル以外に手段がないこと） |
| RAI の Network ルール | Japan East で使えるか、PyPI だけを許可できたか |

- [ ] **Step 1: 【制作者に確認してから】確認用の環境に記憶用のモデルを足す** — Foundry Memory は、チャットのモデルに加えて埋め込みのモデル（`text-embedding-3-small` など）のデプロイを要する。`foundry.bicep` に足し、制作者に「spike の環境に埋め込みモデルのデプロイを足すため `azd provision` を実行します。進めてよいですか」と確認してから実行する。
  Expected: `azd provision` が成功し、`azd env get-values` に埋め込みモデルのデプロイ名が出る

- [ ] **Step 2: 確認 4（グラフ）** — `probe_files.py`: spike-a に「scipy で一次遅れのステップ応答を描き、PNG を返して」と頼み、応答の中のファイル ID を、デプロイした人の ID（Foundry User）で `project.get_openai_client().files.content(<ID>)` から取得する。
  Run: `uv run --no-project --with-requirements scripts/requirements.txt python scripts/probe_files.py`
  Expected（成り立つ条件）: 取得したバイト列の先頭が PNG の印（`\x89PNG`）。成り立たなければ決定 14 は `chart-data`

- [ ] **Step 3: 確認 5（記憶）** — `probe_memory.py`: Memory ストアを1つ作り、scope `integrated_control` に項目を1件足す、scope `motor_control` で検索して出てこない、scope `integrated_control` で検索して出る、項目を消して出なくなる、を順に確かめる。Functions の ID でも同じ権限で動くかは、`probe` キューに `{"kind": "memory"}` を足して確かめる（`function_app.py` の分岐を1つ足す）。
  Expected: 4つとも期待どおり。項目単位の削除ができなければ決定 13 は `cosmos`

- [ ] **Step 4: 確認 7（Routines）** — `probe_routines.py`: spike-a に cron `0 8 * * *`、`Asia/Tokyo` の Routine を作り、`dispatch_async` で起動し、実行の履歴に完了が出ること、harness の会話がどう作られるか（実行ごとに新しい会話か）を記録する。最後に Routine を消す。
  Expected: 作成・手動起動・完了の3つが成り立つ。どれかが成り立たなければ決定 16 は `schedules`

- [ ] **Step 5: 確認 8（A2A）** — `probe_a2a.py`: spike-b の受け側 A2A を有効にし、A2A の道具（相手は spike-b）を持つ `spike-chief` を作る。`spike-chief` の `instance_identity` に Foundry Agent Consumer を付け、「spike-b に whoami の結果を聞いて」と頼む。
  Expected: 応答に spike-b の whoami の結果が入る。成り立たなければ決定 15 は `mail`

- [ ] **Step 6: azd での定義とスキルの添付** — `spikes/harness/azure.yaml` に `azure.ai.agent` のサービスを1つ足し（`AZD_ALPHA_ENABLE_AGENTS_MANAGED_HARNESS=true`）、harness、MCP の道具（接続 `spike-mcp`）、スキル1つを宣言して `azd deploy` する。スキルの登録と添付の方法（API かポータルか）もここで確かめる。
  Expected: できたエージェントが `probe.py mcp` と同じく whoami を呼べる。できなければ、エージェントの定義は `sdk`

- [ ] **Step 7: RAI ポリシーの Network ルール** — Japan East で Network ルールを作り、PyPI のホストだけを許可して spike-a に付ける。`pip install numpy` が通り、`curl https://example.com` が止まることを確かめる。
  Expected: 両方とも期待どおり。作れなければ、設計書 12 節の代わりの方法（絞らずに README に書く）

- [ ] **Step 8: 結果を書き、設計書を直す** — 再検討案 9.1 節に結果と上の決定の表を書く。代わりの方法に切り替えた項目は、設計書の該当の節と 12 節を書き直す。
- [ ] **Step 9: Commit** — `git commit -m "spike: 確認 4、5、7、8 と azd での定義の結果を追記し、設計書の未決事項を決める"`
- [ ] **Step 10: 【制作者に確認してから】確認用の環境を消す** — 「spike の環境を `azd down --purge` で消します。進めてよいですか」と確認し、了承を得たら `spikes/harness` で実行する。Expected: リソースグループとアプリ登録が消える

---

### Task 2: コアの追加（エージェント名、HILS ログ、朝の仕事の整理）

**Files:**
- Modify: `core/src/vehicle_core/constants.py`、`core/src/vehicle_core/clock.py`、`core/src/vehicle_core/seed.py`
- Create: `core/src/vehicle_core/hils_logs.py`
- Test: `core/tests/test_constants.py`（新規）、`core/tests/test_hils_logs.py`（新規）、`core/tests/test_clock.py`、`core/tests/test_seed.py`

**Interfaces:**
- Produces:
  - `agent_name(team: Team) -> str`（`constants.py`）。`AGENT_TEAMS` 以外のチームには `ValueError`
  - `render_hils_log(run: TestRun) -> str`（`hils_logs.py`）。列は `time_ms,brake_pedal_pos,regen_torque_cmd,regen_torque_act,result`。1行目は見出し、行数は 201（0〜2000ms、10ms 刻み）
  - `scenario_log_blobs() -> dict[str, str]`（`hils_logs.py`）。`vehicle_core.scenarios` のすべての試験結果のうち `log_blob` を持つものについて、`log_blob` → CSV
  - `crossed_morning(before: datetime, after: datetime) -> bool`（`clock.py`）。JST で `before < 8:00 の時刻 <= after` となる 8:00 が1つでもあれば真
  - `build_schedules(dataset)`: 決定 16 が `routines` なら、`release_gap_check` だけを返す

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_agent_name_uses_hyphenated_team():
    assert agent_name(Team.INTEGRATED_CONTROL) == "asst-integrated-control"
    assert agent_name(Team.CHIEF_ENGINEER) == "asst-chief-engineer"

def test_agent_name_rejects_team_without_assistant():
    with pytest.raises(ValueError):
        agent_name(Team.BATTERY_CONTROL)

def test_hils_log_is_deterministic_and_shaped():
    run = s2_run(1)  # テスト用の補助関数: シナリオ s2_hils_streak の手順から run-s2-1 の TestRun を取り出す
    csv1, csv2 = render_hils_log(run), render_hils_log(run)
    assert csv1 == csv2
    lines = csv1.strip().splitlines()
    assert lines[0] == "time_ms,brake_pedal_pos,regen_torque_cmd,regen_torque_act,result"
    assert len(lines) == 202

def test_failed_run_log_shows_lagging_actual_torque():
    # 失敗した試験は、指令から実トルクの立ち上がりが 15ms 以上遅れる（シナリオ2の筋書き）
    ...

def test_scenario_log_blobs_cover_s2_runs():
    blobs = scenario_log_blobs()
    assert {f"hils-logs/TC-HILS-031/s2-{n}.csv" for n in (1, 2, 3)} <= blobs.keys()

def test_crossed_morning():
    assert crossed_morning(jst(2026, 11, 17, 21, 10), jst(2026, 11, 18, 8, 0))
    assert not crossed_morning(jst(2026, 11, 18, 8, 0), jst(2026, 11, 18, 9, 0))
    assert crossed_morning(jst(2026, 11, 19, 9, 0), jst(2026, 11, 23, 7, 0))

def test_schedules_keep_only_release_gap_check():  # 決定 16 が routines の場合だけ
    tasks = {s.task for s in build_schedules(build_dataset())}
    assert tasks == {"release_gap_check"}
```

`test_failed_run_log_shows_lagging_actual_torque` の判定: `regen_torque_cmd` が初めて 0 を超えた時刻と、`regen_torque_act` が指令の 63% に初めて達した時刻の差が、`result == "fail"` の試験では 15ms 以上、`pass` の試験では 15ms 未満。

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory core pytest -q` / Expected: 新しいテストが ImportError か AssertionError で FAIL
- [ ] **Step 3: 実装する** — ログは乱数を使わずに作る（指令は 200ms から階段状に立ち上げ、実トルクは一次遅れ。失敗の試験は時定数とむだ時間を大きくする）。Plan 2 の `scripts/seed.py` と `proactive_functions/seeding.py` が朝の仕事の `schedules` を前提にしていないか確かめ、テストを直す
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory core pytest -q && uv run --directory functions pytest -q` / Expected: すべて PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(core): エージェント名、HILS ログの生成、朝 8:00 の判定を足し、朝の仕事を Routines に移す"`

---

### Task 3: MCP の受け口（プロトコル、認証、道具の登録簿）

**Files:**
- Create: `functions/proactive_functions/mcp/__init__.py`、`protocol.py`、`context.py`、`server.py`
- Modify: `functions/function_app.py`
- Test: `functions/tests/test_mcp_protocol.py`、`functions/tests/test_mcp_server.py`、`functions/tests/test_function_app.py`

**Interfaces:**
- Consumes: `TokenVerifier.verify(authorization) -> str`（client ID）、`gateway_http.team_for_client` は Task 4 で `agent_writes.team_for_client(store, client_id) -> str | None` に移る。本タスクでは先に `agent_writes.py` を作り、この関数だけを移す
- Produces:
  - `ToolError(reason: str)`（`context.py`）: 道具が投げると `isError: true` の結果になる
  - `ToolContext`（`context.py`、pydantic、`arbitrary_types_allowed`）: `team: Team`、`store: Store`、`now: datetime`、`memory: Any = None`、`blobs: Any = None`（`memory` は Task 6 の `MemoryBackend`、`blobs` は Task 5 の `BlobReader` を入れる。型はそれぞれのタスクで付ける）
  - `Tool`（`protocol.py`）: `name: str`、`description: str`、`input_schema: dict`、`handler: Callable[[ToolContext, dict], dict | list]`
  - `Registry`（`protocol.py`）: `add(tool: Tool) -> None`、`list() -> list[dict]`（MCP の `tools/list` の形）
  - `handle_rpc(msg: dict, registry: Registry, ctx: ToolContext) -> dict | None`（`protocol.py`）。通知（`id` なし）は `None`
  - `McpHttpResult`（`server.py`、pydantic）: `status: int`、`body: dict | None`
  - `handle_mcp_http(method: str, authorization: str | None, body: bytes, *, verifier: TokenVerifier, store: Store, registry: Registry, make_ctx: Callable[[Team], ToolContext]) -> McpHttpResult`
  - `build_registry() -> Registry`（`server.py`）: 本タスクでは `get_now` だけを登録する。Task 4〜6 が足す
  - 道具 `get_now`: `{"now": <ISO、JST>, "date": "YYYY-MM-DD", "in_quiet_hours": bool}`（静かな時間帯はチームの `team_settings` で判定）

- [ ] **Step 1: 失敗するテストを書く** — spike の `spikes/harness/tests/test_spike_mcp.py` の考え方を引き継ぐ。

```python
def test_initialize_negotiates_known_version(): ...       # 2025-03-26 を求めたら 2025-03-26
def test_initialize_falls_back_to_default_version(): ...   # 1999-01-01 を求めたら 2025-06-18
def test_notification_returns_none(): ...                  # {"jsonrpc":"2.0","method":"notifications/initialized"}
def test_tools_list_returns_registered_tools(): ...        # name、description、inputSchema がそろう
def test_unknown_method_is_jsonrpc_error():                # error.code == -32601
def test_unknown_tool_is_invalid_params():                 # error.code == -32602
def test_tool_error_becomes_is_error_result():
    # handler が ToolError("ほかのチームの文書は書けません") を投げる
    res = handle_rpc(call("deny"), registry, ctx)["result"]
    assert res["isError"] is True and "ほかのチーム" in res["content"][0]["text"]
def test_missing_required_argument_is_is_error_result(): ...  # inputSchema の required が欠けている

def test_http_rejects_missing_token():                     # status 401、registry の handler は呼ばれない
def test_http_rejects_unmapped_client_with_403():          # verify は通るが team_settings にない client ID
def test_http_rejects_non_post_with_405(): ...
def test_http_non_json_body_is_parse_error():              # status 200、error.code == -32700
def test_http_passes_caller_team_to_tools():               # agent_client_id="c-ic" → ctx.team == integrated_control
def test_get_now_uses_virtual_clock_and_quiet_hours():     # now=21:10 JST → in_quiet_hours True
def test_function_app_registers_mcp_and_drops_agent_route(): # 関数名に "mcp" があり "agent_write" がない
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_mcp_protocol.py tests/test_mcp_server.py tests/test_function_app.py -q` / Expected: ImportError か AssertionError で FAIL
- [ ] **Step 3: 実装する** — 必須の引数の検査は `input_schema["required"]` だけを見る（JSON Schema の全面的な検証はしない。型の違いは各道具の pydantic で弾き、`ToolError` にする）。`function_app.py` に `@app.route(route="mcp", methods=["GET","POST","DELETE"], auth_level=ANONYMOUS)` を足し、`agent_write` を消す。トークンもヘッダーの値もログに出さない（呼び出し元のチームと道具の名前だけを出す）
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -q` / Expected: すべて PASS（`test_gateway_http.py` は Task 4 で移すまで残す）
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): MCP サーバーの受け口を足し、HTTP の書き込み窓口のルートを外す"`

---

### Task 4: 書き込みの道具

**Files:**
- Create: `functions/proactive_functions/agent_writes.py`（`gateway_http.py` から移す）、`functions/proactive_functions/mcp/write_tools.py`
- Delete: `functions/proactive_functions/gateway_http.py`、`functions/tests/test_gateway_http.py`（中身は `test_agent_writes.py` に移す）
- Test: `functions/tests/test_agent_writes.py`、`functions/tests/test_mcp_write_tools.py`

**Interfaces:**
- Consumes: Task 3 の `Tool`、`ToolContext`、`ToolError`、`Registry`
- Produces:
  - `agent_writes.py`: `create_doc(store, team, container, doc, now) -> dict`、`replace_run(store, team, run_id, doc, now) -> dict`、`delete_watch(store, team, watch_id) -> None`、`team_for_client(store, client_id) -> str | None`。拒否は `WriteRejected(status: int, reason: str)`（403、404、409 など。Plan 2 の `HttpResult` の理由の文言をそのまま使う）
  - `register_write_tools(registry: Registry) -> None`（`write_tools.py`）。道具と引数（`?` は省略可）:

| 道具 | 引数 | 戻り値 |
|---|---|---|
| `post_message` | `text`、`notification_id?`、`proposal_id?`、`attachments?: list[str]` | `{"id"}` |
| `create_proposal` | `kind`、`to_teams: list[str]`、`draft`、`related_artifact_ids?`、`thread_id?`（なければ新しく作る） | `{"id", "thread_id"}` |
| `record_notification` | `classification`、`reason`、`origin_artifact_id?`、`impacted_ids?` | `{"id", "deliver_at", "delivered_at"}` |
| `start_run` | `title`、`detail?` | `{"run_id"}` |
| `finish_run` | `run_id`、`summary`、`detail?` | `{"run_id"}` |
| `add_watch` | `kind`、`description`、`delivery`、`target_ids?`、`feature?`、`streak?`、`requested_by` | `{"id"}` |
| `remove_watch` | `watch_id` | `{"removed": true}` |
| `add_schedule` | `due_at`、`task`、`payload?` | `{"id"}` |
| `send_mail` | `to_team`、`kind`、`body`、`related_artifact_ids?`、`thread_id?`、`source_message_id?`、`stance?` | `{"id", "thread_id"}` |
| `begin_morning_digest` | なし | `{"already_done": bool, "run_id"?}` |

- [ ] **Step 1: 失敗するテストを書く** — Plan 2 の `test_gateway_http.py` の検査のテストは、`agent_writes` の関数を直接呼ぶ形に書き換えて移す（拒否の理由の文言は変えない）。道具のテストは偽の `Store` と `ToolContext(team=integrated_control, now=2026-11-17 21:10 JST)` で書く。

```python
def test_post_message_ignores_caller_supplied_team_and_author():
    out = call("post_message", {"text": "確認しました", "team": "motor_control", "author": "tanaka", "id": "msg-x"})
    saved = store.get("messages", out["id"])
    assert saved["team"] == "integrated_control" and saved["author"] == "agent" and out["id"] != "msg-x"

def test_send_mail_rejects_impact_notice():
    res = call_raw("send_mail", {"to_team": "motor_control", "kind": "impact_notice", "body": "…"})
    assert res["isError"] is True

def test_create_proposal_for_impact_notice_is_pending(): ...
def test_record_notification_derives_evidence_from_origin():
    # origin = BrkPedalPos の信号 ID。エージェントが impacted_ids=["REQ-999"] を渡しても使わない
    out = call("record_notification", {"classification": "notify_now", "reason": "…",
                                       "origin_artifact_id": SIGNAL_ID, "impacted_ids": ["REQ-999"]})
    n = store.get("notifications", out["id"])
    assert set(n["impacted_ids"]) == set(analyze_impact(graph, SIGNAL_ID).impacted_ids)
def test_record_notification_without_origin_keeps_only_known_ids(): ...
def test_record_notification_in_quiet_hours_is_held_until_morning():  # deliver_at == 翌 8:00、delivered_at is None
def test_finish_run_rejects_other_teams_run(): ...
def test_remove_watch_rejects_other_teams_watch(): ...
def test_wrong_type_argument_is_is_error_not_exception():  # to_teams="motor_control"（文字列）
def test_begin_morning_digest_once_per_virtual_day():
    assert call("begin_morning_digest", {})["already_done"] is False
    assert call("begin_morning_digest", {})["already_done"] is True
    # 仮想の日付が変われば、また False
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_agent_writes.py tests/test_mcp_write_tools.py -q` / Expected: FAIL
- [ ] **Step 3: 実装する** — 各道具は、引数とサーバーが決める値（決定 5）から文書を組み立て、`agent_writes` の関数に渡す。`WriteRejected` は `ToolError(reason)` にする。`add_watch` の `created_by` には `requested_by` を入れる。`finish_run` は既存の記録を読み、`state="done"`、`finished_at=now`、`detail` に `summary` を足して `replace_run` に渡す
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -q` / Expected: すべて PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): 書き込みの道具を MCP に移し、HTTP の書き込み窓口を消す"`

---

### Task 5: 読み取りの道具と HILS ログ

**Files:**
- Create: `functions/proactive_functions/mcp/scope.py`、`functions/proactive_functions/mcp/read_tools.py`、`functions/proactive_functions/blobs.py`
- Modify: `functions/proactive_functions/seeding.py`、`functions/proactive_functions/settings.py`、`scripts/seed.py`
- Test: `functions/tests/test_mcp_scope.py`、`functions/tests/test_mcp_read_tools.py`、`functions/tests/test_seeding.py`

**Interfaces:**
- Consumes: Task 2 の `scenario_log_blobs()`、Task 3 の登録簿
- Produces:
  - `read_scope(container: str) -> Literal["all", "own_or_chief", "own", "members"]`（`scope.py`）。値は設計書 7.5 節の表どおり
  - `effective_team(caller: Team, requested: str | None) -> Team | None`（`scope.py`）: 統括が `requested` を渡したらそのチーム、`None` なら全チーム（`None` を返す）。統括以外は常に `caller`
  - `BlobReader`（`blobs.py`、Protocol）: `read_text(path: str) -> str | None`（`path` は `コンテナ/名前`。ないなら `None`）。実装 `AzureBlobReader(endpoint, credential)`
  - `upload_hils_logs(writer: BlobWriter, logs: dict[str, str]) -> int`（`seeding.py`）。`BlobWriter.write_text(path, text)` は上書き
  - `register_read_tools(registry: Registry) -> None`。道具:

| 道具 | 引数 | 範囲 |
|---|---|---|
| `get_artifact` | `artifact_id` | 全チーム |
| `search_artifacts` | `type?`、`team?`、`text?`（`title` と `description` の部分一致）、`limit?`（既定 50、上限 200） | 全チーム |
| `trace_impact` | `artifact_id` | 全チーム（`ImpactResult` をそのまま） |
| `get_test_runs` | `testcase_id` | 全チーム（新しい順） |
| `get_test_log` | `test_run_id` | 全チーム（`{"csv", "truncated"}`） |
| `get_release_gaps` | `release_id` | 全チーム |
| `list_team_members` | なし | 全チームのメンバーと役割だけ |
| `get_team_settings` | なし | 自チーム（`agent_client_id` は返さない） |
| `list_notifications` | `team?`、`since?` | 自チーム、統括は全チーム |
| `list_proposals` | `team?`、`status?` | 同上 |
| `list_runs` | `team?`、`state?` | 同上 |
| `list_schedules` | `team?` | 同上 |
| `list_mail` | `team?`、`thread_id?` | 自チームが送り手か宛先のもの、統括は全件 |
| `list_messages` | `limit?`（既定 20） | 自チームだけ |
| `list_watches` | なし | 自チームだけ |

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_scope_table_matches_spec():
    assert read_scope("artifacts") == "all"
    assert read_scope("notifications") == "own_or_chief"
    assert read_scope("messages") == "own"
    assert read_scope("team_settings") == "members"

def test_non_chief_team_argument_is_replaced_by_caller():
    out = call("list_notifications", {"team": "motor_control"}, team=Team.INTEGRATED_CONTROL)
    assert {n["team"] for n in out} <= {"integrated_control"}

def test_chief_sees_all_teams_notifications(): ...
def test_list_mail_for_team_includes_sent_and_received_only(): ...
def test_messages_are_own_team_even_for_chief(): ...
def test_team_members_hide_agent_client_id():
    assert all("agent_client_id" not in t for t in call("list_team_members", {}))
def test_get_test_log_returns_csv(): ...
def test_get_test_log_without_blob_is_is_error():          # log_blob が None
def test_get_test_log_missing_blob_is_is_error():          # BlobReader が None を返す
def test_get_test_log_truncates_at_200000_chars(): ...
def test_unknown_artifact_is_is_error(): ...
def test_seed_uploads_scenario_logs(): ...                 # 偽の BlobWriter に s2 の3件が書かれる
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_mcp_scope.py tests/test_mcp_read_tools.py tests/test_seeding.py -q` / Expected: FAIL
- [ ] **Step 3: 実装する** — `Settings` に `blob_endpoint: str`（環境変数 `AZURE_STORAGE_BLOB_ENDPOINT`）を足す。`scripts/seed.py` はシードの投入のあとで `upload_hils_logs` を呼ぶ（デプロイした人に Storage Blob Data Contributor がなければ `storage.bicep` に足す。Functions の ID が `hils-logs` を読めることも確かめる）
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -q` / Expected: すべて PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): 読み取りの道具と HILS ログの投入を足す"`

---

### Task 6: 記憶の道具

**Files:**
- Create: `functions/proactive_functions/mcp/memory.py`
- Modify: `functions/proactive_functions/settings.py`、`infra/modules/cosmos.bicep`（決定 13 が `cosmos` の場合だけ `team_memory` を足す）
- Test: `functions/tests/test_mcp_memory.py`

**Interfaces:**
- Produces:
  - `MemoryItem`（pydantic）: `id: str`、`text: str`、`created_at: AwareDatetime`
  - `MemoryBackend`（Protocol）: `add(scope: str, text: str) -> MemoryItem`、`search(scope: str, query: str | None) -> list[MemoryItem]`、`delete(scope: str, item_id: str) -> bool`（その scope にない ID なら `False`）
  - 実装は Task 1 の決定 13 の1つだけ: `FoundryMemoryBackend(project_endpoint, store_name, credential)` か `CosmosMemoryBackend(store)`。テスト用に `InMemoryBackend` を `tests/fakes.py` に足す
  - `register_memory_tools(registry)`: `remember(text)` → `{"id"}`、`recall(query?)` → `[{"id","text","created_at"}]`、`forget(item_id)` → `{"forgotten": bool}`。scope は常に `ctx.team.value`
  - `Settings` に `memory_backend: Literal["foundry", "cosmos"]`、`memory_store_name: str | None`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_remember_then_recall_in_same_team(): ...
def test_recall_does_not_cross_teams():
    call("remember", {"text": "連絡は朝まとめて"}, team=Team.INTEGRATED_CONTROL)
    assert call("recall", {}, team=Team.MOTOR_CONTROL) == []
def test_forget_other_teams_item_returns_false_and_keeps_it(): ...
def test_scope_argument_is_ignored():
    call("remember", {"text": "x", "scope": "motor_control"}, team=Team.INTEGRATED_CONTROL)
    assert call("recall", {}, team=Team.MOTOR_CONTROL) == []
def test_forget_removes_item_from_recall(): ...   # 設計書 7.7 節「確実に消える」
```

決定 13 の実装クラスにも、本物を使わない単体テストを足す（Foundry なら SDK の呼び出しを偽物で受け、渡した `scope` を確かめる。Cosmos なら偽の `Store` で確かめる）。

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_mcp_memory.py -q` / Expected: FAIL
- [ ] **Step 3: 実装する** — Foundry の場合、Task 1 の `probe_memory.py` で確かめた呼び方をそのまま使う
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -q` / Expected: すべて PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): チームの記憶の道具を足す"`

---

### Task 7: 本物の AgentInvoker と、終わらなかった調査の片付け

**Files:**
- Create: `functions/proactive_functions/foundry_invoker.py`、`functions/proactive_functions/prompts.py`
- Modify: `functions/proactive_functions/investigations.py`（`InvestigationRecord` に `conversation_id: str | None = None`、`response_id: str | None = None`）、`functions/proactive_functions/tick.py`、`functions/proactive_functions/settings.py`、`functions/function_app.py`
- Test: `functions/tests/test_foundry_invoker.py`、`functions/tests/test_prompts.py`、`functions/tests/test_tick.py`

**Interfaces:**
- Consumes: Task 2 の `agent_name(team)`、Plan 2 の `AgentInvoker`、`InvestigationRequest`
- Produces:
  - `investigation_prompt(req: InvestigationRequest, run_id: str, schedules: list[Schedule]) -> str`（`prompts.py`）
  - `ResponsesClient`（Protocol、`foundry_invoker.py`）: `create_conversation() -> str`、`start_response(conversation_id: str, prompt: str) -> str`（応答 ID）、`response_status(response_id: str) -> str`
  - `FoundryResponsesClient(project_endpoint, credential, agent_name)`: spike の `spike_invoke.py` と同じく `project.get_openai_client(agent_name=…)` から `conversations.create()` と `responses.create(conversation=…, input=…, background=True)`、`responses.retrieve(id).status`
  - `FoundryInvoker(store: Store, client_for: Callable[[Team], ResponsesClient], clock: Callable[[], datetime])`: `invoke(request) -> None`（決定 10）
  - `reconcile_runs(store: Store, client_for: Callable[[Team], ResponsesClient], now: datetime) -> list[str]`（決定 11。片付けた作業記録の ID）
  - `Settings.agent_invoker: Literal["log", "foundry"]`、`Settings.foundry_project_endpoint: str | None`（`"foundry"` なら必須）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_prompt_mentions_request_ids_and_run_id():
    p = investigation_prompt(req_s1, "run-inv-abc", [])
    for s in [req_s1.id, req_s1.origin_artifact_id, *req_s1.source_ids, "run-inv-abc", req_s1.floor.value]:
        assert s in p
def test_prompt_for_schedule_includes_task_and_payload(): ...  # release_gap_check と release_id
def test_prompt_tells_agent_to_use_get_now(): ...              # "get_now" を含む
def test_prompt_for_morning_schedule_starts_with_begin_morning_digest(): ...
    # 決定 16 が schedules の場合に、task が morning_digest か morning_briefing なら "begin_morning_digest" を含む

def test_invoke_creates_conversation_starts_background_response_and_records_ids():
    FoundryInvoker(store, lambda t: fake, clock).invoke(req_s1)
    assert fake.calls == [("create_conversation",), ("start_response", "conv-1", ANY)]
    rec = store.get("investigations", req_s1.id)
    assert rec["conversation_id"] == "conv-1" and rec["response_id"] == "resp-1"
    run = store.get("agent_runs", f"run-inv-{req_s1.id}")
    assert run["state"] == "running" and run["detail"]["response_id"] == "resp-1"
def test_invoke_uses_team_agent(): ...                         # client_for に渡るのは req.team
def test_invoke_failure_propagates_so_dispatch_marks_failed(): ...  # Plan 2 の dispatch_due が failed にする
def test_foundry_client_sends_no_harness_managed_params():
    # FoundryResponsesClient.start_response が responses.create に渡すキーは
    # {"conversation", "input", "background"} だけ
def test_reconcile_closes_failed_response(): ...               # status "failed" → state done、detail.error == "failed"
def test_reconcile_closes_completed_but_running(): ...         # detail.closed_by == "tick"
def test_reconcile_leaves_in_progress_and_recent_runs(): ...   # 2 分以内、または in_progress は触らない
def test_settings_require_endpoint_for_foundry_invoker(): ...
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --directory functions pytest tests/test_foundry_invoker.py tests/test_prompts.py tests/test_tick.py -q` / Expected: FAIL
- [ ] **Step 3: 実装する** — 指示文は日本語で、依頼の種類、起点、関係するデータ ID、影響の要約（`impact` があれば、チームごとの件数とリリースへの影響）、知らせ方の下限、`run_id`、「最初に `get_now` を呼ぶ」「調査の最後に `finish_run` を呼ぶ」を書く。`run_tick` の最後で `reconcile_runs` を呼ぶ（`invoker` が `FoundryInvoker` のときだけ）。`function_app._deps` は `AGENT_INVOKER` で `LoggingInvoker` と `FoundryInvoker` を切り替える
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --directory functions pytest -q` / Expected: すべて PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(functions): 調査ごとに会話を作ってエージェントをバックグラウンドで起動する"`

---

### Task 8: エージェントの指示文とスキル

**Files:**
- Create: `agents/instructions/chief_engineer.md`、`integrated_control.md`、`motor_control.md`、`evaluation.md`、`agents/skills/investigate/SKILL.md`、`agents/skills/notify-decision/SKILL.md`、`agents/skills/analysis/SKILL.md`、`agents/skills/analysis/regen_model.py`、`agents/skills/drafting/SKILL.md`、`agents/routines.md`
- Test: `deploy/tests/test_agent_content.py`（`deploy/` は Task 10 で作るメンバー。本タスクで `deploy/pyproject.toml` と空の `proactive_deploy/__init__.py` を先に作る）

**Interfaces:**
- Produces:
  - `agents/skills/analysis/regen_model.py`: `step_delay_ms(signal_period_ms: float) -> float`（ブレーキ操作の信号の周期から、回生トルクの立ち上がりの遅れを返す。numpy と scipy だけを使う）
  - 指示文と `routines.md` は、Task 10 が読む。`routines.md` は見出し `## team` と `## chief_engineer` の2節

内容の決まり（設計書 4、7.4、7.5、7.11 節から）:
- 4体とも: 現在時刻は `get_now` で得る。データは MCP の道具だけから得る。Web 取得とサブエージェントは使わない。開発データを変えない。人の名前を名乗らない。チームの代わりに約束しない
- チームの指示文: 自チームの担当、他チームへの影響を見つけたら `create_proposal`（`impact_notice`）で下書きを作る。受け取った `impact_notice` は自チームの文脈（`list_runs`、`list_team_members`）で解釈し直して `post_message` する
- 統括: 前に出るのは 4.2 節の条件のときだけ。ブリーフィングは3点に絞る。判断案件は両チームの言い分と選択肢を並べる。決定 15 が `a2a` なら A2A の道具で尋ね、`mail` なら `send_mail`（`question`）で尋ねる
- `investigate`: 調べる順序（`get_now` → `trace_impact` → 関係する試験結果と見張り → 判断 → 記録 → `finish_run`）
- `notify-decision`: 3分類の基準（7.4 節）。分類と理由は `record_notification` に必ず書く。配達時刻はサーバーが決めるので、エージェントは静かな時間帯を自分で判断しない
- `analysis`: 作業環境で最初に `pip install numpy scipy matplotlib` を実行する。ログは `get_test_log` で得てファイルに書く。グラフは決定 14 の方法で返す
- `drafting`: 下書きは、起点のデータ ID と影響を受けるデータ ID に触れる。宛先チームの人が読んで何をすればよいかがわかる
- `routines.md`: 最初に `begin_morning_digest` を呼び、`already_done` なら何もせず終える

- [ ] **Step 1: 失敗するテストを書く**

```python
TEAMS = ["chief_engineer", "integrated_control", "motor_control", "evaluation"]

def test_instruction_files_exist_for_every_agent_team(): ...
def test_every_instruction_requires_get_now_and_forbids_web():
    for t in TEAMS:
        text = (AGENTS / "instructions" / f"{t}.md").read_text(encoding="utf-8")
        assert "get_now" in text and "Web 取得" in text
def test_skills_have_frontmatter_name_and_description(): ...
def test_routines_start_with_begin_morning_digest(): ...
def test_tool_names_in_content_exist_in_registry():
    # 指示文とスキルに `xxx` の形で書いた道具名が、build_registry().list() にすべてある
def test_regen_model_reproduces_scenario_delay():
    from regen_model import step_delay_ms
    delta = step_delay_ms(20) - step_delay_ms(10)
    assert 12 <= delta <= 18   # 設計書 7.6 節: 約 15ms
```

- [ ] **Step 2: 失敗を確かめる** — 先に `deploy/pyproject.toml`（name `proactive-deploy`、依存は `vehicle-core`、`proactive-functions`（どちらも workspace）、`azure-ai-projects>=2.10`、`azure-mgmt-authorization`、`azure-identity`、dev に `pytest`）を作り、ルートの `pyproject.toml` の members に `deploy` を足す。
  Run: `uv sync --all-packages && uv run --package proactive-deploy pytest deploy/tests/test_agent_content.py -q` / Expected: FAIL
- [ ] **Step 3: 書く** — 文章は yomiyasu の書き方に沿う。スキルの形式（frontmatter の項目）は Task 1 の「スキルの添付」で確かめた形に合わせる
- [ ] **Step 4: 通ることを確かめる** — 同じコマンド / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(agents): 4体の指示文、共通のスキル、回生協調の簡易モデルを足す"`

---

### Task 9: インフラ（Foundry のプロジェクトとロール）

**Files:**
- Create: `infra/modules/foundry.bicep`（`spikes/harness/infra/modules/foundry.bicep` をもとにする）
- Modify: `infra/main.bicep`、`infra/main.parameters.json`、`infra/modules/functions.bicep`

**Interfaces:**
- Produces（azd の環境の値）: `FOUNDRY_PROJECT_ENDPOINT`、`FOUNDRY_PROJECT_ID`、`AZURE_AI_PROJECT_ID`（`FOUNDRY_PROJECT_ID` と同じ値。`azd ai connection create` が使う）、`MODEL_DEPLOYMENT`、`EMBEDDING_DEPLOYMENT`（決定 13 が `foundry` の場合だけ）、既存の `GATEWAY_APP_ID_URI`、`FUNCTION_APP_URL`
- Functions のアプリ設定に足すもの: `AGENT_INVOKER=foundry`、`FOUNDRY_PROJECT_ENDPOINT`、`MEMORY_BACKEND`、`MEMORY_STORE_NAME`（`foundry` の場合）、`AZURE_STORAGE_BLOB_ENDPOINT`

作るもの:
- Foundry のアカウント（`kind: AIServices`、`allowProjectManagement: true`、`disableLocalAuth: true`）とプロジェクト `proj-proactive`、モデルのデプロイ（既定 `gpt-5.4-mini`、`2026-03-17`、GlobalStandard、容量 50。`MODEL_NAME` / `MODEL_VERSION` で変えられる）
- ロール（プロジェクトのスコープ）: デプロイする人に Foundry User と Foundry Project Manager、Functions の ID に Foundry User
- 決定 13 が `foundry` なら埋め込みモデルのデプロイ

- [ ] **Step 1: Bicep を書く**（インフラなので単体テストの RED-GREEN はない）
- [ ] **Step 2: 構文を確かめる** — Run: `az bicep build --file infra/main.bicep --stdout > /dev/null` / Expected: エラーなし（警告は README に理由を書けるものだけ）
- [ ] **Step 3: アプリ設定の名前がコードと合うことを確かめる** — `functions.bicep` に足した設定の名前が、`load_settings` の読む名前（Task 5〜7 で足したもの）とすべて一致することを目で突き合わせ、Run: `uv run --directory functions pytest -q` / Expected: すべて PASS
- [ ] **Step 4: Commit** — `git commit -m "feat(infra): Foundry のアカウント、プロジェクト、モデル、ロールを足す"`

---

### Task 10: デプロイのフック（接続、エージェント、ロール、対応表、Routines）と時計の操作

**Files:**
- Create: `deploy/proactive_deploy/definitions.py`、`roles.py`、`setup.py`
- Modify: `pyproject.toml`（members に `deploy`）、`deploy/pyproject.toml`、`azure.yaml`、`scripts/clock.py`、`README.md`
- Test: `deploy/tests/test_definitions.py`、`deploy/tests/test_roles.py`、`deploy/tests/test_setup.py`、`functions/tests/test_clock.py` か `scripts` のテスト（`crossed_morning` を使う部分）

**Interfaces:**
- Consumes: Task 2 の `agent_name`、`crossed_morning`、Task 3〜6 の `build_registry()`（道具名の一覧）、Task 8 の `agents/`、Task 9 の環境の値、Plan 2 の `scripts/_azd.py`
- Produces:
  - `AgentSpec`（pydantic、`definitions.py`）: `name: str`、`team: Team`、`instructions: str`、`skills: list[str]`、`mcp_allowed_tools: list[str]`、`a2a_targets: list[str]`
  - `agent_specs(root: Path, tool_names: list[str], ask_mode: Literal["a2a", "mail"]) -> list[AgentSpec]`（4件。`a2a` のとき統括の `a2a_targets` はほかの3体の名前、それ以外は空）
  - `RoleGrant`（pydantic）: `principal_id: str`、`role_definition_id: str`、`scope: str`
  - `role_grants(project_id: str, identities: dict[Team, str], ask_mode) -> list[RoleGrant]`: 4体それぞれに Foundry User。`a2a` なら統括に Foundry Agent Consumer（ロール ID は着手時に Learn で確かめる）
  - `assignment_name(grant: RoleGrant) -> str`（`roles.py`）: `uuid5(NAMESPACE_URL, scope|principal|role)`。同じ grant なら同じ名前
  - `apply_grants(client, grants) -> list[str]`（`roles.py`）: 既にあるもの（`RoleAssignmentExists`）は成功として扱う
  - `sync_agent_client_ids(store: Store, identities: dict[Team, str]) -> list[str]`（`setup.py`）: `team_settings` の `agent_client_id` を書き、変えたチームを返す
  - `routine_specs(root: Path) -> list[RoutineSpec]`（決定 16 が `routines` の場合だけ）: 4体それぞれ、cron `0 8 * * *`、`Asia/Tokyo`、指示文は `routines.md` の該当の節
  - `main() -> None`（`setup.py`）: 次の順に行い、各段の結果を表示する。どの段も何度実行してもよい
    1. `azd ai connection create proactive-mcp --kind remote-tool --target {FUNCTION_APP_URL}/api/mcp --auth-type agentic-identity --audience {GATEWAY_APP_ID_URI} --force --no-prompt -p {FOUNDRY_PROJECT_ENDPOINT}`（spike の `setup_agents.py` と同じ）
    2. エージェント4体を作る（定義が `sdk` なら `create_version`、`azd` なら azd のサービスが作ったものを読む）
    3. `instance_identity` を読み、`role_grants` を `apply_grants` する
    4. `sync_agent_client_ids`
    5. Routines を作る（決定 16 が `routines` の場合）
    6. RAI ポリシーを作って付ける（Task 1 で使えた場合）
  - `scripts/clock.py`: 時計を進めたとき `crossed_morning(前, 後)` が真なら、4体の Routines を `dispatch_async` で起動する（決定 16 が `routines` の場合）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_agent_specs_cover_four_teams_with_all_tools():
    specs = agent_specs(AGENTS, ["get_now", "post_message"], "mail")
    assert {s.name for s in specs} == {"asst-chief-engineer", "asst-integrated-control",
                                       "asst-motor-control", "asst-evaluation"}
    assert all(s.mcp_allowed_tools == ["get_now", "post_message"] for s in specs)
def test_only_chief_gets_a2a_targets_in_a2a_mode(): ...
def test_role_grants_give_foundry_user_to_each_agent(): ...
def test_role_grants_add_agent_consumer_to_chief_only_in_a2a_mode(): ...
def test_assignment_name_is_stable(): ...
def test_apply_grants_treats_existing_assignment_as_success(): ...
def test_sync_agent_client_ids_updates_only_changed_teams_and_keeps_other_fields(): ...
def test_routine_specs_use_tokyo_8am(): ...                    # 決定 16 が routines の場合
def test_clock_dispatches_routines_only_when_crossing_8am(): ... # 偽の dispatcher
```

- [ ] **Step 2: 失敗を確かめる** — Run: `uv run --package proactive-deploy pytest deploy/tests -q` / Expected: FAIL
- [ ] **Step 3: 実装する** — `azure.yaml` に `postdeploy: uv run --package proactive-deploy python -m proactive_deploy.setup` を足す（Plan 2 の `postprovision` のシード投入は残す）。定義が `azd` なら、Task 1 の雛形から `agents/<エージェント名>/agent.yaml` を4つ作り、`azure.yaml` のサービスに足す（`AZD_ALPHA_ENABLE_AGENTS_MANAGED_HARNESS=true` を README に書く）。ロールの割り当ては `azure-mgmt-authorization` で行う（az CLI に JSON を渡さない）
- [ ] **Step 4: 通ることを確かめる** — Run: `uv run --package proactive-deploy pytest deploy/tests -q && uv run --directory functions pytest -q && uv run --directory core pytest -q` / Expected: すべて PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(deploy): MCP 接続、エージェント4体、ロール、対応表、Routines を作るフックを足す"`

---

### Task 11: Azure 上での確認と README

**Files:**
- Modify: `scripts/smoke.py`、`README.md`、`docs/superpowers/plans/2026-11-08-plan3-foundry-agents.md`（末尾に「実装時の決定」を追記）

**Interfaces:**
- Produces（`scripts/smoke.py` に足す確認。Plan 2 の確認のうち、HTTP の書き込み窓口の 401 の確認は、MCP の 401 の確認に置き換える）:
  1. `seed_store(reset=True)`
  2. トークンなしの `POST {FUNCTION_APP_URL}/api/mcp` が 401
  3. 4体の `instance_identity` の principal ID が、Cosmos の SQL ロールの割り当て（`az cosmosdb sql role assignment list`）に1つもない（設計書 9 節「権限」）
  4. 時計を 2026-11-17 21:10 JST に合わせて `ce-s1-1` を書き、21:14 に進める。10 分以内に、統合制御の `agent_runs`（`run-inv-…`）が `done` になり、`notifications` に `origin_artifact_id` が BrkPedalPos の信号で、`classification` が `notify_now` の通知が1件でき、`deliver_at` が 2026-11-18 08:00 JST
  5. `proposals` に、統合制御から `impact_notice`（宛先にモーター制御を含む、`status: pending`）が1件以上ある
  6. 時計を 2026-11-18 08:00 に進める。Routines（決定 16 が `routines` の場合）か `schedules` で朝のまとめが起動し、5 分以内に `run-morning-integrated_control-20261118` ができる。もう一度手動起動しても、統合制御の朝のまとめのメッセージは増えない
  7. 最後に `seed_store(reset=True)`

- [ ] **Step 1: スモークテストを書く**（Azure 上の確認なので RED-GREEN はない。待ち合わせは5秒ごとに読み直し、上限時間で打ち切る。LLM の文章は判定しない）
- [ ] **Step 2: 【制作者に確認してから】デプロイしてスモークテストを流す** — 制作者に「`proactive-dev` に `azd up` で Foundry とエージェント4体を足し、デモ用のデータをリセットしてスモークテストを流します。モデルの呼び出しの費用が少しかかります。進めてよいですか」と確認する。了承を得たら:
  Run: `azd up`、続けて `uv run --package proactive-functions python scripts/smoke.py`
  Expected: `SMOKE OK`。4〜6 が通らないときは、Foundry のポータルでエージェントのトレース（どの道具を呼び、何が `isError` になったか）と、Application Insights の `mcp` 関数のログを見て原因を突き止めてから直す。指示文やスキルを直した場合は、Task 8 のテストも流す
- [ ] **Step 3: README を更新する** — yomiyasu の書き方で、次を足す・直す:
  - 構成図と「エージェントは Cosmos DB に触れない」こと（設計書 6.1、7.5 節）
  - 前提に `azure.ai.agents` 拡張と、必要なら `AZD_ALPHA_ENABLE_AGENTS_MANAGED_HARNESS`
  - プレビュー機能の一覧（設計書 10 節）と、Task 1 で代わりの方法に切り替えたもの
  - 予定の仕組みが2つ（Routines と `schedules`）ある理由（設計書 7.3 節）
  - 使ったモデルと理由（設計書 8 節）
  - エージェントを作り直したとき、フックが対応表とロールを合わせ直すこと
- [ ] **Step 4: 実装時の決定を追記する** — 本書の末尾に「実装時の決定」を足す（Task 1 の決定の表、実装中に決めたこと、Plan 4 への申し送り: BFF の ID に Foundry User、チャットの会話 ID の置き場所、グラフの取得方法、Memory ストアの読み方）
- [ ] **Step 5: Commit** — `git commit -m "docs: Plan 3 のデプロイ手順と確認を README に追記し、スモークテストを足す"`
