# spike: harness 付きエージェントの確認（使い捨て）

[再検討案](../../docs/superpowers/specs/2026-11-08-foundry-rearchitecture-proposal.md)の 9 節にある確認のうち、D1（エージェントの動かし方）を左右する2つを確かめる環境です。ついでに 3 も見ます。本番の azd 環境（`proactive-dev`）とは別の環境に作り、終わったら消します。

| 番号 | 確かめること | 成り立つ条件 |
|---|---|---|
| 2 | MCP 接続（`agentic-identity`）で Functions の MCP サーバーを呼んだとき、トークンで2体を区別できるか | `whoami` の結果が `verified: true` で、spike-a と spike-b で `oid`（または `azp` / `sub`）が違い、それぞれ `instance_identity` と対応する |
| 6 | Functions から harness 付きエージェントを人の操作なしで起動できるか | `queue` の結果が `completed`。`background` を受け付けるかも記録する（受け付けなければ、同期で待つ設計にする） |
| 3（ついで） | 作業環境で numpy / scipy / matplotlib が使えるか | `invoke` の出力に3つの版が出る |

## 作るもの

- Foundry のアカウントとプロジェクト（キーは無効）、モデルのデプロイ（既定は `gpt-5.4-mini`、`MODEL_NAME` / `MODEL_VERSION` で変えられる）
- Functions（Flex Consumption）: MCP サーバー（`/api/mcp`、道具は `whoami` だけ）と、キュー `probe` を受けてエージェントを起動する関数
- MCP サーバーのトークンの宛先にする Entra アプリ登録
- Storage、Application Insights、ユーザー割り当てマネージド ID

ロールは、デプロイする人に Foundry User と Foundry Project Manager（プロジェクト）、キューへの投入と結果の読み取り（Storage）を付けます。Functions の ID には Foundry User を付けます。

## 手順（PowerShell）

```powershell
cd spikes/harness
azd env new proactive-spike --location japaneast
azd up

# MCP 接続とエージェント2体を作る（エージェントの instance_identity が表示される）
uv run --no-project --with-requirements scripts/requirements.txt python scripts/setup_agents.py

# spike 2
uv run --no-project --with-requirements scripts/requirements.txt python scripts/probe.py mcp
# spike 6（と 3）
uv run --no-project --with-requirements scripts/requirements.txt python scripts/probe.py invoke --mode sync
uv run --no-project --with-requirements scripts/requirements.txt python scripts/probe.py invoke --mode background
uv run --no-project --with-requirements scripts/requirements.txt python scripts/probe.py queue --mode background
```

結果は `results/` に JSON で残ります（ID などが入るのでコミットしない）。要点は再検討案の 9 節に書き足します。

## 片付け

```powershell
azd down --purge
```

Entra のアプリ登録も消えます。Foundry のアカウントは `--purge` で論理削除の状態から完全に消します。

## テスト

```powershell
uv run --no-project --with pytest --with-requirements mcp/requirements.txt pytest -q tests
```
