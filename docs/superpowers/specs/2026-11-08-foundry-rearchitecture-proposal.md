# Foundry の機能を最大限使うためのアーキテクチャ再検討（提案）

- 状態: **決定済み（2026-11-08）**。D1〜D4 は推奨どおりに決まり、[設計書の第2版](2026-11-07-proactive-vehicle-agent-design.md)に反映した。この文書は判断の経緯として残す
- 調査日: 2026-11-08。出典はすべて Microsoft Learn（各節にリンク）
- 書いた人: Claude。【Claude判断】は私の推奨、【要決定】は制作者に決めてほしいこと

---

## 0. 要約

1. **4体のエージェントを、ホステッドエージェント（自前のコンテナ）から「Copilot harness を使うプロンプトエージェント」に変える。** エージェント本体のコードは書かない。指示文、スキル、ツールの宣言だけで作り、azd でデプロイする
2. **決まった手順で求まる処理（影響範囲の計算、書き込みの検査）は、Functions 上の MCP サーバーにまとめる。** エージェントには Toolbox（または MCP ツール）として渡し、エージェントごとの ID（エージェント ID）で認証する。エージェントには Cosmos DB への権限を一切与えない
3. **解析は Container Apps Sandboxes をやめ、harness が会話ごとに用意する作業環境（shell）で行う。** 必要なライブラリがそろわなければ Code Interpreter を使う
4. **毎朝の定時の仕事は Foundry の Routines に移す。**
5. **Foundry に代わりがないものは今のまま残す。** Cosmos の変更フィードを起点にした振り分け・まとめ、エージェント間メールの配達、承認（proposals と BFF）、Web PubSub、仮想の時計
6. 3つの食い違いがあるので、制作者に決めてほしい（5節）
   - harness では Foundry Memory を直接使えない
   - Routines は実時間で動き、デモの仮想の時計とは合わない
   - harness はプレビューで、作ったあとに実行形態を切り替えられない

---

## 1. 調べてわかったこと（設計に効く事実だけ）

| 機能 | 設計に効く事実 | 出典 |
|---|---|---|
| Copilot harness（プレビュー） | プロンプトエージェントの実行環境を Foundry が運用する。harness のツールはファイルの読み書き、shell、Web 取得、サブエージェントの5つ。ほかにスキル、関数ツール、Web 検索、Toolbox 経由のツールが使える | [Copilot harness の使い方](https://learn.microsoft.com/azure/foundry/agents/how-to/use-tools-skills-copilot-harness) |
| 〃 | 提供地域に **Japan East が入っている**。モデルは推論とツール呼び出しに対応したもの。BYOM は不可 | [制限と地域](https://learn.microsoft.com/azure/foundry/agents/concepts/limits-quotas-regions#microsoft-copilot-harness-preview) |
| 〃 | **Foundry Memory は使えない**（Memory ストアもメモリツールも不可）。会話の履歴と作業環境のファイルは使える | 同上 |
| 〃 | 作業環境は会話ごとに分かれる。サンドボックスが休止・再開・置き換えされても中身は残る。CPU やメモリは設定できない | 同上 |
| 〃 | 呼び出しはエージェントのエンドポイントのみ。毎回 `conversation` が必要。`store: false` と `previous_response_id` は不可。`temperature` などは指定できない。未対応の項目はエラーになる | 同上 |
| 〃 | 実行形態（harness か否か）は作るときに選ぶ。既存のエージェントは切り替えられない | 同上 |
| 〃 | 作業環境から外への直接通信は、RAI ポリシーの Network ルールで許可先を絞れる（プレビュー） | [harness の安全設定](https://learn.microsoft.com/azure/foundry/agents/how-to/use-tools-skills-copilot-harness#secure-tools-and-data) |
| 〃 | 生成したファイルは Foundry Files に上げて返す。エージェントの `instance_identity.principal_id` に、プロジェクトの Foundry User ロールが要る。**このロールはエージェントを作ったあとでしか割り当てられない** | [ファイルの受け渡し](https://learn.microsoft.com/azure/foundry/agents/how-to/use-tools-skills-copilot-harness#exchange-files-with-the-agent) |
| 関数ツール | 関数ツールは、呼び出したアプリ側が実行して結果を返す仕組み | [関数呼び出し](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/function-calling) |
| Toolbox | MCP、OpenAPI、A2A、Code Interpreter、Web 検索、ファイル検索、スキルなどを1つの MCP エンドポイントにまとめる。`require_approval` の強制は呼び出す側の責任で、Toolbox は止めない | [Toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox) |
| MCP の認証 | 接続の認証方式に `agentic-identity`（エージェントごとの ID）がある。複数のエージェントに別々の権限を持たせたいときに使う、と明記されている | [MCP の認証](https://learn.microsoft.com/azure/foundry/agents/how-to/mcp-authentication#microsoft-entra-authentication) |
| エージェント ID のトークン | エージェント ID のトークンには `xms_par_app_azp`（作成元のブループリント）が入る。普通のアプリのトークンには入らない | [下流 API での検証](https://learn.microsoft.com/entra/agent-id/how-to-validate-agent-tokens-downstream-api) |
| Routines | トリガー1つで、エージェント1体を呼ぶ。トリガーは一度きりの時刻、cron（最短5分）、イベント（GitHub の Issue と Teams のみ）。`time_zone` を指定できる。`:dispatch_async` で手動で起動できる。1回の試行の待ち時間は30秒（Responses ではバックグラウンド実行の受け付けまで） | [Routines の概要](https://learn.microsoft.com/azure/foundry/agents/concepts/routines)、[使い方](https://learn.microsoft.com/azure/foundry/agents/how-to/use-routines) |
| 〃 | Japan West では使えない。**Japan East は除外一覧に入っていない** | 同上 |
| 〃 | Routines からの起動は、エンドポイントの認証方式が `AzureRbac`（Entra）である必要がある。プレビューの `AgentBlueprint` 方式では起動できない | 同上 |
| リマインダー | エージェントが自分で「何分後にもう一度起こして」と予約できるツール。**ホステッドエージェント専用**で、プロンプトエージェントでは使えない | [Toolbox のリマインダー](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox) |
| ワークフロー | Foundry のワークフローは独立したエージェントの種類ではなくなる方向。移行先は Agent Framework（ホステッドエージェントとしてデプロイ）か Logic Apps、または A2A での直接呼び出し | [ワークフローの移行ガイド](https://learn.microsoft.com/azure/foundry/agents/concepts/workflow#migration-guide) |
| 人の承認（プレビュー） | 長時間実行のホステッドエージェントが、人の返事を待って止まり、続きから再開できる（`@multi_turn_task`）。ホステッドエージェント専用 | [human-in-the-loop](https://learn.microsoft.com/azure/foundry/agents/how-to/add-human-in-the-loop) |
| A2A（v1.0 は GA） | プロンプトエージェントは Responses を標準で公開しているので、受け側の A2A を有効にできる。呼ぶ側の ID に、受け側プロジェクトの Foundry Agent Consumer ロールが要る。テキストのみ、ストリーミング不可 | [受け側の A2A](https://learn.microsoft.com/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint)、[A2A ツール](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/agent-to-agent) |
| Foundry Memory（プレビュー） | **Japan East で使える**。Memory ストアの API で、項目単位の追加・更新・削除と検索ができる。scope で区切る | [Memory の概要](https://learn.microsoft.com/azure/foundry/agents/concepts/what-is-memory#region-availability)、[使い方](https://learn.microsoft.com/azure/foundry/agents/how-to/memory-usage) |

---

## 2. 部品ごとの比較（現行 → 提案）

| 役割 | 現行の設計書 | 提案 | 理由 |
|---|---|---|---|
| エージェント本体 ×4 | ホステッドエージェント（Python、Agent Framework、同じコードを4回デプロイ） | **harness 付きプロンプトエージェント ×4**。指示文はチームごと、スキルは共通 | ランタイムのコードとコンテナが要らなくなる。作業環境、ファイル、スキルを Foundry が運用する |
| 手順の決まった処理（影響範囲の計算など） | エージェントのコード内のツール | **Functions 上の MCP サーバー**のツール。中身は vehicle_core をそのまま使う | プロンプトエージェントは自前のコードを持てない。関数ツールは「呼び出したアプリが実行する」ので、Routines や Functions から起動したときに実行する人がいない（4節の制約1） |
| 書き込み窓口 | Functions の HTTP 関数（Plan 2 で実装済み） | **同じ検査を MCP ツールとして公開する**。認証はエージェント ID | 検査の中身（vehicle_core.gateway）は変わらない。入り口が HTTP から MCP に変わる |
| エージェントのデータ読み取り | エージェントの ID に Cosmos の読み取り権限 | **読み取りも MCP ツール経由**。エージェントには Cosmos の権限を一切与えない | harness の作業環境から Cosmos の SDK を認証付きで使う手段が確認できない。記事では「エージェントは Cosmos に一切触れない」と書けるようになる |
| 解析 | Container Apps Sandboxes（外部通信なし、Blob をマウント） | **harness の作業環境（shell）**。足りなければ **Code Interpreter**（Toolbox） | 調査1件を会話1本にすれば、作業環境が調査ごとに分かれ、後日の再開もできる（現行の「一時停止して再開」と同じ性質）。外への通信は RAI ポリシーで止める |
| 解析結果のグラフ | Blob に保存して会話に添付 | **Foundry Files**（harness が上げる）→ BFF が取得して画面に出す | harness の標準の返し方 |
| チームの記憶 | Foundry Memory（scope はチーム ID） | 【要決定 D2】推奨は **Memory ストアの API を MCP ツールで包む**（Functions が scope＝チーム ID で読み書き） | harness は Memory を直接使えない。Foundry Memory 自体は使い続けられる |
| 毎朝のまとめ・ブリーフィング | Functions のタイマーと `schedules` | 【要決定 D3】推奨は **Routines**（cron、`Asia/Tokyo`） | Foundry 側に実行履歴とトレースが残る。デモでは `:dispatch_async` で手動起動する |
| リリース前チェック、エージェントが入れた「後で見る」予定 | `schedules` + tick | **今のまま**（`schedules` + tick） | プロンプトエージェントはリマインダーを使えず、Routines を自分で作る手段もない。日付が仮想の時計に結びついている |
| 変更の振り分け・まとめ | Functions（変更フィード） | **今のまま** | Routines のイベントは GitHub と Teams だけ。Cosmos の変化では起動できない |
| エージェント間の「知らせる」 | `agent_mail` + 変更フィード | **今のまま** | 同上。全件が残り、統括が写しを読める点も変わらない |
| エージェント間の「尋ねる」 | A2A | **A2A のまま**（プロンプトエージェントの受け側 A2A + 統括に A2A ツール）。認証はエージェント ID（アプリとしての呼び出し） | 利用者に代わって呼ぶ方式（`AgentOnBehalfOfUser`）は `AgentBlueprint` 方式が必要で、Routines の起動と両立しない |
| 人の承認 | `proposals` → 人が承認 → BFF が実行 | **今のまま** | 「実行は決まったコードが行う」という線引きが記事の柱。Foundry の承認待ち（長時間実行）はホステッド専用で、再開後に実行するのはエージェント自身になる |
| エスカレーション | `agent_mail` の `escalation` | **今のまま** | 条件は単純な規則。ワークフローは移行中の機能で、使う理由が弱い |
| 画面への即時通知 | Web PubSub | 今のまま | — |
| 会話 | 各アシスタントの Responses。会話 ID はチームに1本 | **チャットはチームに1本、調査は1件に1本**。どちらもエージェントのエンドポイントに `conversation` 付きで送る | harness は会話が必須。調査ごとに作業環境を分けたい |
| 外への通信の制限 | Sandbox の外部通信を止める | **RAI ポリシーの Network ルール**で、作業環境からの直接通信を止める | harness の標準の仕組み |
| 監視 | App Insights | App Insights + Foundry のトレース（プロンプトエージェントは標準で出る） | — |
| 品質の確かめ方 | シナリオテスト（本物の LLM） | 今のまま。Foundry の評価（azd の評価機能）は【任意】で後から足す | 判定は構造化された結果で行う方針を変えない |

---

## 3. 全体図（提案）

```
                    ┌──────────── Web アプリ（Container Apps）──────────────┐
 人 ── ブラウザ ──▶ │ 画面（会話・マップ・見張り） + API（BFF）              │
        ▲           └──┬──────────────┬─────────────┬───────────────────┘
        │ 即時通知      │ 会話           │ 承認の実行    │ 読み取り / グラフ取得
        │ (Web PubSub)  ▼ (Responses)   │              ▼
        │   ┌─────────────────────────────────────────────────────────┐
        │   │ Foundry プロジェクト（Japan East）                            │
        │   │  プロンプトエージェント ×4（Copilot harness）                   │
        │   │   車種統括 / 統合制御 / モーター制御 / 評価                     │
        │   │   ・共通スキル（調査の進め方、知らせ方の判断、解析の手順）         │
        │   │   ・会話ごとの作業環境（shell、ファイル）← 解析はここ           │
        │   │   ・統括 → 各チームへ A2A で尋ねる                             │
        │   │  Routines: 毎朝 8:00 のまとめ・ブリーフィング                   │
        │   │  Memory ストア（scope＝チーム）／ Foundry Files（グラフ）        │
        │   │  RAI ポリシー（作業環境の外部通信を止める）                       │
        │   └──────┬──────────────────────────────────▲───────────────┘
        │          │ MCP ツール（エージェント ID で認証）    │ 調査の依頼（バックグラウンド）
        │          ▼                                   │
        │   ┌─────────────────────────────────────────┴──────┐
        └───│ Azure Functions                                  │
            │ ・MCP サーバー: 読み取り、影響範囲の計算、           │
            │   検査付きの書き込み、記憶の読み書き                 │
            │ ・変更フィード: 振り分け、まとめ、メール配達、画面通知 │
            │ ・tick: 仮想の時計、`schedules`、静かな時間帯の配達   │
            └──────────────┬───────────────────────────────┘
                           ▼
                    ┌──────────────┐
                    │  Cosmos DB   │ 開発データ・通知・提案・メールなど
                    └──────────────┘
```

なくなるもの: ホステッドエージェントのコンテナ、Container Apps Sandboxes、エージェントへの Cosmos 読み取り権限。

---

## 4. 提案から導かれる制約（設計の決まりとして書き足すもの）

1. **関数ツールは使わない。ツールはすべてサーバー側で動くもの（MCP、Toolbox、宣言型のツール）にする。** 関数ツールは呼び出したアプリが実行して結果を返す仕組みなので、Routines や Functions のバックグラウンド起動では誰も実行しない
2. **エージェントは Cosmos DB に直接アクセスしない。** 読み書きのすべてが MCP サーバーを通る。MCP サーバーはトークンからチームを判定し、Plan 2 と同じ検査をする
3. **エージェントのエンドポイントの認証方式は Entra（`AzureRbac`）にする。** Routines の起動に必要。そのため A2A は「エージェント ID でのアプリとしての呼び出し」に限る
4. **調査1件に会話1本。** 作業環境とファイルが調査ごとに分かれる。チャットはチームに1本の会話を共有する（現行どおり）
5. **harness が管理する項目は指定しない。** `temperature`、`max_output_tokens`、`truncation` など。指定するとエラーになる
6. **エージェントを作ったあとに、ロールの割り当てが要る。** エージェントの `instance_identity.principal_id` へのプロジェクトの Foundry User（Toolbox と Files 用）は、エージェントができてからでないと割り当てられない。Bicep だけでは完結せず、azd の postdeploy フックで割り当てる

---

## 5. 決めてほしいこと

### D1. エージェントの実行形態【要決定】
| 案 | 良い点 | 弱い点 |
|---|---|---|
| **A. harness 付きプロンプトエージェント（推奨）** | エージェントのコードが要らない。作業環境・スキル・ファイルを Foundry が運用。Routines と受け側 A2A に対応。「Foundry の機能で作る」という今回の狙いに一番合う | プレビュー。Memory を直接使えない。リマインダーなし。細かい生成設定ができない。作業環境の性能は選べない |
| B. ホステッドエージェント（現行） | Memory、リマインダー、長時間実行と承認待ちが使える。動きを自分のコードで決められる | コンテナとランタイムのコードを持つ。解析には別に Sandboxes か Code Interpreter が要る |

【Claude判断】A を推奨する。影響範囲の計算や検査は、もともと「LLM にさせずコードで求める」方針（設計書 7.1）なので、そのコードを MCP サーバー側に置けば、エージェント側にコードがなくても方針は崩れない。

### D2. チームの記憶【要決定】
| 案 | 内容 |
|---|---|
| **A. Memory ストアを MCP ツールで包む（推奨）** | Functions が Memory ストアの API を scope＝チーム ID で呼ぶ。`remember` / `forget` / `recall` をツールにする。Foundry Memory を使い続けられる。抽出と統合を Memory に任せるか、項目の直接操作だけにするかは spike で決める |
| B. Cosmos に `team_memory` を作る | 確実で単純。ただし Foundry の機能は使わない |
| C. D1 で B（ホステッド）を選び、Memory を直接使う | 設計書どおり |

### D3. 定時の仕事と仮想の時計【要決定】
Routines は実時間の cron で動く。デモは「翌朝」「7日前」を仮想の時計で再現している。

| 案 | 内容 |
|---|---|
| **A. 併用（推奨）** | 毎日の決まった仕事（朝のまとめ、ブリーフィング）だけ Routines（`0 8 * * *`、`Asia/Tokyo`）。デモで時計を進めたときは、越えた時刻の Routines を `:dispatch_async` で手動起動する。リリース前チェックとエージェントの「後で見る」予定は `schedules` + tick に残す。**予定の仕組みが2つ並ぶ**ことは記事で説明する |
| B. 全部 Functions（現行） | 仕組みは1つで済む。Routines は使わない |
| C. 仮想の時計をやめる | 全部 Routines と実時間。デモは手動起動でつなぐ。静かな時間帯やシナリオの日付の扱いを作り直す必要がある |

### D4. 解析の環境【要決定、spike の結果しだい】
| 案 | 内容 |
|---|---|
| **A. harness の作業環境 → 足りなければ Code Interpreter（推奨）** | spike で numpy / scipy / matplotlib（python-control は必須でない。一次遅れのモデルは scipy で書ける）が使えるか確かめる。使えなければ Code Interpreter を Toolbox で足す（harness のツール設定とは独立に動くと明記されている） |
| B. Container Apps Sandboxes を残す | ライブラリ入りのイメージを持ち込める。Foundry の外の部品が1つ残る |

---

## 6. 採らなかったもの

| 機能 | 採らない理由 |
|---|---|
| Foundry のワークフロー | 独立した種類ではなくなり、Agent Framework か Logic Apps へ移る途中。エスカレーションの条件は単純な規則なので、`agent_mail` で足りる |
| 長時間実行の承認待ち（`@multi_turn_task`） | ホステッド専用。再開後に実行するのがエージェント自身になり、「実行は決まったコードが行う」線引きが弱くなる |
| リマインダー | ホステッド専用 |
| Routines のイベント起動 | GitHub と Teams だけ。制作者には M365 テナントがない |
| 関数ツール | 4節の制約1 |
| harness のサブエージェントで A2A を置き換える | サブエージェントが「別の Foundry エージェント」を指すのか確認できていない。尋ねる手段は A2A のまま |
| Logic Apps | 承認や長時間の処理は既存の proposals と Functions で足りる。部品が増える |

---

## 7. 作り済みのコードへの影響

**Plan 1（vehicle_core）: 変更なし。** 影響範囲の計算、書き込みの規則、配達時刻の判断、データモデルは、MCP サーバーからそのまま使う。

**Plan 2（インフラと Functions）: 大半は残る。変わるのは次のとおり。**

| 対象 | 変更 |
|---|---|
| `gateway_http.py`（書き込み窓口） | 検査の中身は残す。入り口を MCP ツールにする（HTTP を残すかは spike で決める） |
| 読み取り | MCP ツールを新しく足す（データの取得、影響範囲の計算、チームの見張り・作業記録の取得） |
| `auth.py`（トークン検証） | 今はアプリ登録のトークンを想定し、`azp`/`appid` を `TeamSettings.agent_client_id` に対応づけている。**エージェント ID のトークンでどのクレームがエージェントを指すかは未確認**（`xms_par_app_azp` はブループリントを指す）。そのまま使えるかは spike で確かめる |
| `investigations.py` の `AgentInvoker` | 今は記録だけの `LoggingInvoker`。本物は「調査1件ごとに会話を作り、エージェントのエンドポイントへバックグラウンドで Responses を送る」実装にする。Functions の ID に Foundry のロールが要る |
| `tick.py` と `seed.py` | D3 で A を選んだ場合、朝のまとめとブリーフィングの `schedules`（`sch-digest-*`、`sch-briefing-*`）を消し、Routines に移す。リリース前チェックは残す |
| `scripts/clock.py` | D3 で A の場合、時計を進めたときに越えた Routines を手動起動する |
| インフラ（Bicep / azd） | 足すもの: Foundry のアカウントとプロジェクト、モデルのデプロイ、プロンプトエージェント ×4、スキル、Toolbox、MCP 接続（`agentic-identity`）、Routines、RAI ポリシー、ロールの割り当て（postdeploy フック）。外すもの: Container Apps Sandboxes の予定、エージェントへの Cosmos 読み取り権限の予定 |

**Plan 3（エージェント）: 中身が大きく変わる。** 「ホステッドエージェントの Python コード」から「MCP サーバー + スキル + 指示文 + azure.yaml の宣言」になる。計画は作り直す。

**Plan 4（Web アプリ）: 小さな変更。** 会話の送り先がエージェントのエンドポイントになる。グラフは Foundry Files から取る。

---

## 8. プレビューと地域

| 機能 | 状態 | Japan East |
|---|---|---|
| Copilot harness | プレビュー（作成後に切り替え不可） | 提供地域に入っている |
| Foundry Memory | プレビュー | 提供地域に入っている |
| スキル | プレビュー（ポータル表記） | harness と同じ前提 |
| RAI ポリシーの Network ルール | プレビュー（API `2026-05-15-preview`） | 未確認 |
| Routines | 着手時に提供状況を確認 | 除外一覧（UK West、Switzerland West、Japan West、UAE North、Norway East）に入っていない |
| A2A v1.0 | GA | — |
| Toolbox | 着手時に確認 | 道具ごとの地域対応表で確認する |

設計書 10 節のとおり、プレビューを使う箇所は記事と README に書く。

---

## 9. 計画を作り直す前に確かめること（spike）

確認は使い捨ての環境で行い、結果をこの文書に書き足す。

1. **harness 付きプロンプトエージェントを Japan East に azd で作れるか**（`AZD_ALPHA_ENABLE_AGENTS_MANAGED_HARNESS=true`、azd 1.37.0 以上）。使えるモデルも確かめる
2. **MCP 接続（`agentic-identity`）で Functions の MCP サーバーを呼んだとき、トークンに何が入るか。** 4体でエージェントを区別できるクレームがあるか。Functions の MCP 拡張で自前のトークン検証ができるか（できなければ HTTP 関数で MCP を受ける）
3. **作業環境で numpy / scipy / matplotlib が使えるか。** 使えなければ Code Interpreter で同じ解析ができるか
4. **グラフを Foundry Files で返し、BFF の ID で取得できるか**
5. **Functions から Memory ストアの API を scope＝チーム ID で読み書きできるか**（D2 で A の場合）
6. **Functions から harness 付きエージェントをバックグラウンドで起動できるか。** harness の制限表にバックグラウンド実行は書かれていないが、できるとも書かれていない
7. **Routines を `Asia/Tokyo` の cron で作り、`:dispatch_async` で手動起動できるか**（D3 で A の場合）
8. **harness 付きエージェントで受け側の A2A を有効にし、統括から呼べるか**（ドキュメントはプロンプトエージェント一般について書いており、harness での確認はない）

spike の結果、2 か 6 が成り立たない場合は、D1 を B（ホステッド）に戻すことを提案する。

### 9.1 結果（2026-11-08、環境 `proactive-spike`、Japan East、モデル gpt-5.4-mini）

環境とスクリプトは [spikes/harness](../../../spikes/harness/README.md)。エージェントは SDK（`azure-ai-projects` 2.10.0、`PromptAgentDefinition(harness=MicrosoftCopilotHarness())`）で作った。

| 番号 | 結果 | わかったこと |
|---|---|---|
| 2 | **成り立つ** | MCP サーバーに届いたトークンは v2.0。`aud` はアプリ登録の app ID（GUID。`api://…` の URI ではない）。`azp` / `oid` / `sub` はどれもエージェントの `instance_identity`（principal_id と client_id は同じ値）で、spike-a と spike-b で値が違う。JWKS による署名と宛先の検証は、HTTP 関数で自前で行って通った。**Plan 2 の `auth.py`（`azp` を `team_settings.agent_client_id` と照らす）は、そのまま使える。** `agent_client_id` には `instance_identity.client_id` を入れる。`xms_par_app_azp`、`idtyp`、`roles` はトークンに入っていなかった。そのため「エージェントからの呼び出しか」はクレームでは判定できず、許可は `azp` の対応表だけが根拠になる（Plan 2 の考え方と同じ）。MCP の要求には `mcp-method`、`mcp-name`、`mcp-protocol-version` のヘッダーが付き、エージェント名のヘッダーはない |
| 6 | **成り立つ** | harness 付きエージェントは `background=True` を受け付けた（受け付けた直後は `in_progress`、ポーリングで `completed`）。Functions のマネージド ID（プロジェクトに Foundry User）からも、キューで起動して完了まで確かめた。かかった時間は 10〜25 秒 |
| 3 | **条件付きで成り立つ** | 作業環境は Python 3.13.17 で、numpy は最初は入っていない。シェルで `pip install numpy scipy matplotlib` を実行すると、既定のネットワーク設定のまま入った（numpy 2.5.4、scipy 1.18.1、matplotlib 3.11.2、20 秒ほど）。作業環境は会話ごとに別なので、解析のたびに入れ直す。RAI ポリシーで外向きの通信を絞る場合は、PyPI のホストを許可に入れる。Code Interpreter で代える必要はない |
| 1 | 一部だけ | Japan East で harness 付きエージェントを作り、gpt-5.4-mini で動いた。ただし azd の `azure.ai.agent` サービスではなく SDK で作ったので、azd での定義は Plan 3 の最初に確かめる。`azd ai connection create` は、azd の環境に `AZURE_AI_PROJECT_ID` がないと失敗する |
| 4、5、7、8 | 9.2 節 | Plan 3 の Task 1 で確かめた |

そのほかに見えたこと:

- エージェントの `agent_endpoint.authorization_schemes` は、既定で `Entra` だった。Routines は Entra（AzureRbac）の方式を求めるので、既定のまま使えるとみられる（7 で確かめる）
- エージェントを作ると、エージェントごとに別のブループリント（`blueprint.client_id`）もできた

**結論: 2 と 6 が成り立ったので、D1 は A（harness）で進める。D4 も A（作業環境で pip install）でよい。**

### 9.2 結果（2026-11-08、Plan 3 Task 1、同じ環境）

スクリプトは `spikes/harness/scripts/probe_*.py`。

| 確認 | 結果 | わかったこと |
|---|---|---|
| 4 グラフ | **成り立つ** | harness には組み込みの道具 `upload_file_from_workspace_to_foundry_project` があり、結果の `function_call_output` に `{"file_id": "assistant-…", "filename", "bytes"}` が入る。取得は**プロジェクトの** OpenAI クライアント（`project.get_openai_client().files.content(<ID>)`）で行い、Foundry User を持つ自分の ID で PNG（53 KB）が取れた。エージェントのエンドポイント用のクライアント（`get_openai_client(agent_name=…)`）からは 404。アップロードには、エージェントの `instance_identity` にプロジェクトの Foundry User が要る |
| 5 記憶 | **成り立つ（ロールの追加が要る）** | 手元の ID と Functions の ID の両方で、scope の分離、検索、一覧、削除を確かめた。最初は埋め込みモデルの呼び出しが 401 で失敗した。通ったのは、呼び出す ID（自分、Functions）にアカウントのスコープで Cognitive Services OpenAI User を付け、プロジェクトとアカウントのマネージド ID にアカウントのスコープで Foundry User と Cognitive Services OpenAI User を付けたあと（どれが必須かは切り分けていない）。項目 ID は「scope 名の base64 + `_` + ランダム」で、**削除は項目 ID だけでできる**。そのため MCP サーバーは、消す前に ID が呼び出し元の scope のものかを確かめる |
| 7 Routines | **成り立つ（会話は指定しない）** | cron `0 8 * * *`、`Asia/Tokyo` で作成でき、自分の ID からも Functions の ID（Foundry User だけ）からも `dispatch` で起動できた。会話を指定しない Routine は、**起動のたびに新しい会話を作り**、エージェントは MCP の道具を呼んだ（`list_runs` に `conversation_id` と `response_id` が出る）。自分が作った会話を指定した Routine は 404 で失敗した |
| 8 A2A | **成り立つ** | spike-b の受け側 A2A を `update_details` で有効にし、接続（`RemoteA2A`、認証 `AgenticIdentityToken`、宛先 `https://ai.azure.com`、ARM の PUT）を作り、`A2ATool(a2a_version=V1_0, project_connection_id=…)` を持つ spike-chief から頼むと、spike-b の ID で whoami が呼ばれた。spike-chief の `instance_identity` に Foundry Agent Consumer（`eed3b665-ab3a-47b6-8f48-c9382fb1dad6`）を付け、5 分待った |
| 決定 2 | `True` | Foundry は `server/discover`、`initialize`、`notifications/initialized`、`tools/list`、`tools/call` のすべてに、検証できるトークンを付けていた |
| azd での定義 | **できる** | `azd ai agent init --kind prompt --harness microsoft_copilot_preview --project-id <ID>` で既存のプロジェクト（`host: azure.ai.project`、`endpoint`）を参照する `azure.yaml` ができ、MCP の道具（`project_connection_id` に接続名）、スキル（`host: azure.ai.skill`）、道具の絞り込みを足して `azd deploy` できた。ただし生成される `azure.yaml` は `infra.provider: microsoft.foundry` で、本番の Bicep の構成と1つにまとめる方法は確かめていない |
| スキル | **できる** | `project.beta.skills.create(name=…, inline_content=SkillInlineContent(description=…, instructions=…))` で作り、`PromptAgentDefinition(skills=[SkillReference(name=…)])` で付けると、エージェントがスキルの中身を答えた |
| harness の道具 | **外せる** | `tools` に `MicrosoftCopilotToolsetPreview(default_config=…(enabled=False), configs=[…filesystem_read / filesystem_write / shell を enabled=True])` を入れると、Web 取得は使えなくなった。ただし Web 取得を外しても、エージェントはシェルの `curl` で同じページを取りに行った。外への通信を止めるのは RAI ポリシーの役目 |
| RAI の Network ルール | **Japan East で使える** | `Microsoft.CognitiveServices/accounts/raiPolicies`（`2026-05-15-preview`）に `egressPolicy`（`defaultAction: Deny`、`pypi.org` と `files.pythonhosted.org` を許可）を PUT し、`RaiConfig(rai_policy_name=<ARM の ID>)` で付けると、`pip install numpy` は通り、`curl https://example.com` は 403 になった |

**Plan 3 の決定の表**

| 決定 | 結果 |
|---|---|
| 13 記憶 | `foundry` |
| 14 グラフ | `foundry-files` |
| 15 尋ねる | `a2a` |
| 16 Routines | `routines`（会話は指定しない） |
| エージェントの定義 | `sdk`（azd でもできるが、理由は設計書 7.10 節） |
| スキルの添付 | `project.beta.skills.create` と `SkillReference` |
| RAI の Network ルール | Japan East で使える。PyPI だけを許可できた |
| harness の道具 | 外せる（`MicrosoftCopilotToolsetPreview`） |
| 決定 2 | `DISCOVERY_REQUIRES_TOKEN = True` |
| 決定 17 | Functions の ID（プロジェクトの Foundry User）で手動起動できた。追加のロールは要らない |

---

## 10. 承認後の進め方

1. 5節の決定と9節の spike の結果をもとに、設計書（6節・7節・10節）を書き直す
2. Plan 2 の小さな手直し（MCP 化、AgentInvoker の本実装、`schedules` の整理）を Plan 3 の最初のタスクに入れる
3. Plan 3（エージェント）を作り直す。Plan 4 は会話の送り先とグラフの取得だけ直す
