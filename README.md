# proactive-agent

架空の自動車メーカーで新型 EV の制御ソフトウェアを開発している、という設定の PoC です。開発データの変化を見張り、領域をまたぐ影響を調べて、関係するチームとチーフエンジニアに頼まれる前に知らせるエージェントを、Microsoft Foundry（Copilot harness を使うプロンプトエージェント）、Azure Functions、Cosmos DB で作ります。

## 状態

Plan 4 まで実装しました。画面からシナリオを1手ずつ進めて、エージェントの動きを見られます。

- `core/`: Azure も LLM も使わずに動く判定ロジックと架空データ（Plan 1）
- `functions/` と `infra/`: Azure の基盤と Functions（Plan 2、3）。データの変更を受けて調査依頼を作り、エージェントを起動します。エージェントの道具（MCP サーバー）もここにあります
- `agents/`: エージェント4体の指示文、共通のスキル4つ、朝の Routines の指示文（Plan 3）
- `deploy/`: エージェント、スキル、ロール、Routines などを作る azd のフック（Plan 3）
- `web/`: 画面（React）と BFF（FastAPI）。1つのコンテナーにして Container Apps で動かします（Plan 4）

- 設計書: [docs/superpowers/specs/2026-11-07-proactive-vehicle-agent-design.md](docs/superpowers/specs/2026-11-07-proactive-vehicle-agent-design.md)
- 実装計画: [docs/superpowers/plans/](docs/superpowers/plans/)

## 構成

```
 Web アプリ（Container Apps。サインインは組み込み認証）
   ・画面: 会話とカード、影響マップ、作業の見える化、デモの操作
   ・BFF: 画面の状態、承認、チャット、シナリオの再生（Cosmos DB と Foundry をマネージド ID で使う）
        │ チャット（バックグラウンド）、グラフの取得、記憶の一覧
        ▼
 Foundry プロジェクト（Japan East）
   プロンプトエージェント ×4（Copilot harness）: 車種統括 / 車両統合制御 / モーター制御 / 評価
     ・共通スキル（調査の進め方、知らせ方の判断、解析の手順、下書きの書き方）
     ・会話ごとの作業環境（シェルとファイル）。解析はここで行う
     ・統括は各チームのアシスタントに A2A で尋ねる
   Routines: 毎朝 8:00 のまとめとブリーフィング
   Memory ストア（scope はチーム）、Foundry Files（グラフ）、RAI ポリシー（外への通信は PyPI だけ）
        │ MCP の道具（エージェント ID のトークンで認証）      ▲ 調査の依頼（バックグラウンド）
        ▼                                              │
 Azure Functions
   ・MCP サーバー: 読み取り、影響範囲の計算、検査付きの書き込み、記憶の読み書き
   ・変更フィード: 振り分け、まとめ、メールの配達、画面への通知
   ・tick: 仮想の時計、予定、静かな時間帯の配達、時計を進めたときの Routines の起動
        │
        ▼
 Cosmos DB（開発データ、通知、提案、エージェント間メールなど）
```

### エージェントは Cosmos DB に触れない

エージェントの ID には、Cosmos DB の権限を一切与えていません。読み取りもできません。読み書きはすべて Functions の MCP サーバーの道具を通ります。MCP サーバーは、トークンの `azp`（エージェントの client ID）を `team_settings.agent_client_id` と照らして呼び出し元のチームを決め、書ける対象と読める範囲をチームごとに絞ります。たとえば、他チームへの影響の連絡（`impact_notice`）はエージェントが直接送れず、下書きにして人の承認を待ちます。

エージェントを作り直すとエージェント ID が変わります。`postdeploy` のフックは毎回、エージェント ID の client ID を `team_settings` に書き直し、ロールを割り当て直します。

### 予定の仕組みが2つある理由

| 仕事 | 仕組み |
|---|---|
| 毎朝 8:00 のチームのまとめと、車種統括のブリーフィング | Foundry Routines（エージェント1体に1つ、cron `0 8 * * *`、`Asia/Tokyo`） |
| 統合リリースの7日前の抜け漏れチェック、エージェントが自分で入れた予定 | Cosmos DB の `schedules` と、Functions の tick |

毎日決まった時刻の仕事は Routines で動かせます。一方、リリースの期日に結びついた仕事は、デモの仮想の時計に合わせて動く必要があります。また、プロンプトエージェントは Routines を自分で作れないので、エージェントが入れる予定は MCP の道具で `schedules` に書きます。

デモで時計を進めて朝 8:00 を越えたときは、tick が4体の Routines を手動で起動します。Routines 自身の cron は実時間の毎朝 8:00 に起動しますが、エージェントがまとめを作るのは、仮想の時刻が朝（8:00〜11:59）のときだけです。仮想の時計は実時間からずれているので、cron が仮想の夜中に起動しても、何もせずに終わります。そのため、時計を動かさずに仮想の 8:00 を迎えても、朝のまとめは出ません。デモでは時計を朝に進めてください。

朝のまとめは「仮想の日付 + チーム」で1日1回に限るので、手動起動と cron が重なっても二重には届きません。途中で失敗して作業記録が「いま」のまま 15 分たったときは、次の起動が引き継いでやり直します。

### モデル

`gpt-5.4-mini`（GlobalStandard）を使います。harness に使えるのは推論とツール呼び出しに対応したモデルだけで、確認用の環境ではこのモデルで道具の呼び出しと作業環境での解析が動きました。生成の設定（温度など）は harness が決めるので、品質はモデルの選択と、指示文とスキルで調整します。振り分けや配達時刻の判定は LLM を使わずにコードで行うので、小さいモデルを別に用意していません。モデルは `azd env set MODEL_NAME …` と `MODEL_VERSION` で変えられます。

容量（レートの上限）は 500（50 万トークン/分）にしています。harness は1回の呼び出しに指示文、スキル、道具の定義を毎回入れるので、1回が大きくなります。朝 8:00 に4体が同時に動くと、50 では足りずに `rate_limit_exceeded` で応答が途中で失敗しました。GlobalStandard は使った分だけの課金なので、容量を上げても固定費は増えません。サブスクリプションの割り当てが足りないときは、`infra/main.bicep` の `modelCapacity` を下げてください。

Memory ストアの索引には `text-embedding-3-small` を使います。

### プレビューの機能

次のプレビューの機能を使っています（2026-11-08 時点）。

- Copilot harness（プロンプトエージェント）と、harness の道具の絞り込み（`MicrosoftCopilotToolsetPreview`）
- スキル
- Foundry Memory の Memory ストア
- Foundry Routines
- RAI ポリシーの Network ルール（外への通信の制限）
- A2A（エージェント間通信）

確認用の環境（`spikes/harness/`）で、どれも Japan East で動くことを確かめたので、代わりの方法に切り替えたものはありません。エージェントの定義だけは、azd の `azure.ai.agent` サービスでもできることを確かめたうえで、フックの SDK で作っています（下の「手順」）。

## 開発

[uv](https://docs.astral.sh/uv/) が必要です。テストは Azure なしで動きます。

```bash
uv sync --all-packages
uv run --directory core pytest
uv run --directory functions pytest
uv run --package proactive-deploy pytest deploy/tests
uv run --directory web pytest
cd web/frontend && npm ci && npm test
```

画面は Azure なしでも確かめられます。BFF をメモリーの Store と決まった返事を返すチャットで起動し、シナリオ1の朝（配達済みの通知、承認待ちの提案）の状態から始めます。

```bash
cd web/frontend && npm run build && cd ../..   # 画面を web/proactive_web/static に組み立てる
uv run --package proactive-web python -m proactive_web.dev   # http://127.0.0.1:8000
```

画面を直しながら見るときは、BFF を起動したまま `cd web/frontend && npm run dev` を使います（`/api` は BFF に中継します）。

## Azure へのデプロイ

### 前提

- Azure サブスクリプション
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)、[Azure Developer CLI（azd）](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) 1.37 以降、uv
- azd の拡張 `azure.ai.connections`（フックが MCP 接続を作るのに使う）。`azd extension install azure.ai.connections` で入れます
- Entra ID でアプリ登録を作れる権限。書き込み窓口のトークンの宛先にするため、Bicep（Microsoft Graph 拡張）でアプリ登録を1つ作ります
- サブスクリプションでロールを割り当てられる権限（所有者、またはユーザーアクセス管理者）

### 手順

```bash
azd auth login
azd env new proactive-dev --location japaneast
azd up
```

`azd up` は次の順に進みます。

1. Bicep でリソースを作る（Foundry のアカウント、プロジェクト、モデルのデプロイを含む）
2. デモのデータ（シード）を Cosmos DB に入れる（`postprovision`）
3. Functions（MCP サーバーを含む）をデプロイする
4. Web アプリのイメージを、azd がコンテナーレジストリの中で組み立てて（リモートビルド）、Container Apps に配置する
5. `postdeploy` のフック（`deploy/proactive_deploy/setup.py`）が、Bicep では作れないものを作る。MCP 接続、RAI ポリシー（外への通信は PyPI だけ）、スキル4つ、エージェント4体、エージェント ID へのロール、`team_settings.agent_client_id`、Memory ストア、朝の Routines の順です。何度実行してもかまいません

エージェントの定義は、フックの Python スクリプトから SDK で作ります。azd の `azure.ai.agent` サービスでも harness、MCP の道具、スキルを宣言できますが、指示文をチームごとのファイルから読みたいことと、ロールや Routines のためにフックがどのみち要ることから、SDK にしています（設計書 7.10 節）。

フックだけをやり直すときは、次のコマンドを実行します。

```bash
uv run --package proactive-deploy python -m proactive_deploy.setup
```

初回の `azd up` が「`azd-service-name: functions` のタグが付いたリソースが見つからない」というエラーで止まることがあります。azd がプロビジョニングと並行して発行を始めるためです。リソースはできているので、`azd deploy` だけをもう一度実行してください。

片付けるときは次のコマンドで、作ったものをすべて消します。

```bash
azd down --purge
```

`azd up` のあと、`azd env get-value WEB_URL` が画面の URL です。

### 地域

`japaneast`（東日本）を使います。この PoC で使う次のものがすべて使える地域だからです（2026-11-08 時点）。確認用の環境の Japan East で、harness 付きエージェント、Memory ストア、Routines、RAI ポリシーの Network ルール、A2A が動きました。

- Foundry の Copilot harness、Foundry Memory、Routines
- Azure Functions の Flex Consumption プラン
- Azure Web PubSub

### 費用

使わないときの費用は、ほぼゼロです。

- Cosmos DB はサーバーレスで、読み書きした分だけかかります
- Functions は Flex Consumption で、常に起動しておくインスタンスを置いていません
- Web PubSub は Free 枠、Storage は LRS です
- Container Apps は、使わないときゼロ台まで縮みます。最初に開いたときは起動に数秒かかります
- コンテナーレジストリ（Basic）だけは、使わなくても月に数百円かかります

ただし Functions は、1分ごとのタイマーで「時刻に関わる仕事」（夜に保留した知らせの配達、朝の仕事）を確かめ続けます。1回の処理は短く、Flex Consumption の無料枠に収まる見込みです。

モデルは呼び出した分だけかかります。エージェントを呼ぶのは、調査の依頼、エージェント間メール、画面からの会話、朝の Routines のときです。Routines は実時間でも毎朝 8:00 に4体を起動するので、使っていない日も1日4回の呼び出しがかかります。止めたいときは Foundry のポータルで Routines を無効にするか、`azd down --purge` で片付けてください。

### キーを使わない

接続にはキーや接続文字列を使いません。Foundry、Cosmos DB、Storage、Web PubSub、Application Insights はキーでの接続を無効にし、Functions はマネージド ID で接続します。エージェントは、自分のエージェント ID のトークンで MCP サーバーを呼びます。MCP サーバーはトークンの署名、宛先、テナントを検証してから道具を動かします。

### サインイン

画面のサインインは Container Apps の組み込み認証（Entra ID）です。サインインできるのは、`azd up` を実行した人だけです。Bicep がサインイン用のアプリ登録に「割り当てた人だけ」を設定し、デプロイした人を割り当てます。デモのデータを消して作り直す操作があるので、テナントの全員には開いていません。ほかの人に見せるときは、Entra 管理センターの「エンタープライズ アプリケーション」で `proactive-agent web (<環境名>)` にユーザーを追加してください。

組み込み認証はクライアントシークレットなしで設定しています。キーや接続文字列を持たない方針に合わせるためです。シークレットがないと、組み込み認証は ID トークンだけを受け取る暗黙的フローでサインインします。Microsoft は暗黙的フローを勧めていません。この PoC では架空のデータしか扱わず、BFF はトークンを外の API に渡さないので、この形にしています。本番で使うなら、シークレットか証明書を Key Vault に置いて認可コードフローにしてください。

## 画面

画面を開いたら、上の帯の「誰として見るか」で人物を選びます。田中（車両統合制御）、佐藤（モーター制御）、鈴木（評価）、高橋（チーフエンジニア）の4人です。選んだ人物はブラウザーに覚えます。上の帯には、リリースまでの日数と仮想の時刻も出ます。

- 左: アシスタントとの会話。提案つきのメッセージにはカードが付き、「送る」「直す」「今回は送らない」で他チームへの影響の連絡を承認します。下の入力欄からアシスタントに話しかけられます
- 中央: 影響マップと、アシスタントの作業（いま、予定、完了）。マップでは、メッセージを選ぶと起点を塗りつぶし、影響を受けるデータを赤枠、チームをまたぐつながりを赤い点線で示します
- 右: 見張っていること、話しかける頻度の設定、アシスタントが覚えていること
- 上の帯の「デモの操作」: シナリオの手順の一覧、「次へ」、最初からやり直す

高橋の画面では、チーフエンジニアの判断が要ること（`notify_now` の通知にひもづくメッセージ）を会話欄の先頭に並べます。高橋が見るのは、全チームの通知と作業、自分あての会話と提案です。

### 事前の承認

他チームへの影響の連絡（`impact_notice`）は、毎回人が承認してから送ります。自チームの人へのメッセージ（朝のまとめなど）は、もともと承認なしで届きます。設計書 7.5 節の「事前の承認」にあたる新しい仕組みは作っていません。

## シナリオの進め方

設計書 5.3 節の5つのシナリオを、決まった順に1手ずつ進めます。画面の「デモの操作」の「次へ」と、次の CLI は同じ仕組みです。どちらも Azure 上のデータを書き換えます。

```bash
uv run --package proactive-web python scripts/scenario.py list          # 手順の一覧（済んだものに印）
uv run --package proactive-web python scripts/scenario.py next --wait   # 次の手順を行う
uv run --package proactive-web python scripts/scenario.py reset         # 最初からやり直す（データを作り直す）
```

「次へ」は、手順の時刻まで仮想の時計を進めてから手順を行います。前提が揃っていなければ、何も変えずに理由を返します。

- 時計を進める手順は、夜の調査が終わるまで待ちます。変更やメールから作られるはずの調査依頼がまだない、または調査の作業記録が終わっていないときです。夜の調査の途中で朝にすると、エージェントが朝の時刻で通知を記録してしまい、朝まで保留する筋書きが崩れます
- 承認の手順は、承認待ちの影響の連絡ができるまで待ちます。画面で先に承認していれば、その提案で済ませます
- 人の発言の手順は、そのチームのアシスタントが前の返事を書き終えるまで待ちます

シナリオテストは、5つのシナリオを最初から通し、手順ごとの期待値（`web/proactive_web/scenario_checks.py`）を確かめます。データを作り直し、モデルを何十回も呼ぶので、40 分ほどかかり、費用も少しかかります。終わったあともデータを残すので、画面で結果を見られます。

```bash
uv run --package proactive-web python scripts/scenario_test.py
```

## デモのデータと時計

デモでは「翌朝 8:00」や「リリースの 7 日前」を待たずに再現するため、システム全体が仮想の時計を使います。現在時刻は「実時間 + ずれ」で、ずれは Cosmos DB の `system` コンテナーにあります。時計を合わせると、Functions がすぐに時刻に関わる仕事を進めます。

```bash
# デモのデータを入れる（足りない文書だけ作る）
uv run --package proactive-functions python scripts/seed.py

# デモのデータをすべて消して作り直す（時計も 2026-11-17 18:00 に戻る）
uv run --package proactive-functions python scripts/seed.py --reset

# 仮想時計の表示と設定
uv run --package proactive-functions python scripts/clock.py show
uv run --package proactive-functions python scripts/clock.py set 2026-11-18T08:00:00+09:00

# Azure 上の流れを通して確かめる（デモのデータを作り直す）
uv run --package proactive-functions python scripts/smoke.py
```

登場する会社、車種、人物、データはすべて架空のものです。
