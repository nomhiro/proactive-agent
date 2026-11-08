# proactive-agent

架空の自動車メーカーで新型 EV の制御ソフトウェアを開発している、という設定の PoC です。開発データの変化を見張り、領域をまたぐ影響を調べて、関係するチームとチーフエンジニアに頼まれる前に知らせるエージェントを、Microsoft Foundry（ホステッドエージェント）、Azure Functions、Cosmos DB、Container Apps Sandboxes で作ります。

## 状態

実装中です。Plan 2 まで済んでいます。

- `core/`: Azure も LLM も使わずに動く判定ロジックと架空データ（Plan 1）
- `functions/` と `infra/`: Azure の基盤と Functions（Plan 2）。データの変更を受けて調査依頼を作り、時刻を見て配達や朝の仕事を進めます。エージェント本体（Plan 3）はまだないので、調査依頼はログに出すだけです

- 設計書: [docs/superpowers/specs/2026-11-07-proactive-vehicle-agent-design.md](docs/superpowers/specs/2026-11-07-proactive-vehicle-agent-design.md)
- 実装計画: [docs/superpowers/plans/](docs/superpowers/plans/)

## 開発

[uv](https://docs.astral.sh/uv/) が必要です。テストは Azure なしで動きます。

```bash
uv sync --all-packages
uv run --directory core pytest
uv run --directory functions pytest
```

## Azure へのデプロイ

### 前提

- Azure サブスクリプション
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)、[Azure Developer CLI（azd）](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) 1.37 以降、uv
- Entra ID でアプリ登録を作れる権限。書き込み窓口のトークンの宛先にするため、Bicep（Microsoft Graph 拡張）でアプリ登録を1つ作ります
- サブスクリプションでロールを割り当てられる権限（所有者、またはユーザーアクセス管理者）

### 手順

```bash
azd auth login
azd env new proactive-dev --location japaneast
azd up
```

`azd up` はリソースを作り、Functions をデプロイし、最後にデモのデータ（シード）を Cosmos DB に入れます。

初回の `azd up` が「`azd-service-name: functions` のタグが付いたリソースが見つからない」というエラーで止まることがあります。azd がプロビジョニングと並行して発行を始めるためです。リソースはできているので、`azd deploy` だけをもう一度実行してください。

片付けるときは次のコマンドで、作ったものをすべて消します。

```bash
azd down --purge
```

### 地域

`japaneast`（東日本）を使います。この PoC で使う次の 5 つがすべて使える地域だからです（2026-11-08 時点）。

- Foundry のホステッドエージェント
- Foundry Memory（プレビュー）
- Container Apps Sandboxes
- Azure Functions の Flex Consumption プラン
- Azure Web PubSub

### 費用

使わないときの費用は、ほぼゼロです。

- Cosmos DB はサーバーレスで、読み書きした分だけかかります
- Functions は Flex Consumption で、常に起動しておくインスタンスを置いていません
- Web PubSub は Free 枠、Storage は LRS です

ただし Functions は、1分ごとのタイマーで「時刻に関わる仕事」（夜に保留した知らせの配達、朝の仕事）を確かめ続けます。1回の処理は短く、Flex Consumption の無料枠に収まる見込みです。

### キーを使わない

接続にはキーや接続文字列を使いません。Cosmos DB、Storage、Web PubSub、Application Insights はキーでの接続を無効にし、Functions はマネージド ID で接続します。エージェントからの書き込みは、Entra ID のトークンを検証する Functions の HTTP 関数（書き込み窓口）だけが受け付けます。

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
