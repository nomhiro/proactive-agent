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

## Plan 3 Task 1 の確認（4、5、7、8 ほか）

結果は再検討案の 9.2 節。`uv run --no-project --with-requirements scripts/requirements.txt python <スクリプト>` で流す（Windows では `PYTHONIOENCODING=utf-8` を付ける）。

| スクリプト | 確かめること |
|---|---|
| `scripts/probe_mcp_methods.py` | MCP のどのメソッドにトークンが付くか（先に `probe.py mcp` を流す） |
| `scripts/probe_files.py` | グラフを Foundry Files で返し、自分の ID で取得できるか |
| `scripts/probe_memory.py` | Memory ストアを scope＝チームで読み書きできるか（自分と Functions の ID） |
| `scripts/probe_routines.py` | Routines の作成と手動起動（自分と Functions の ID） |
| `scripts/probe_a2a.py` | 受け側の A2A と、A2A の道具での呼び出し |
| `scripts/probe_agent_config.py` | スキルの添付、harness の道具の絞り込み、RAI ポリシーの外向き通信の制限 |

記憶の確認のために、Bicep の外で次のロールを手で付けた（`az role assignment create`）: 自分と Functions の ID にアカウントのスコープで Cognitive Services OpenAI User、プロジェクトとアカウントのマネージド ID にアカウントのスコープで Foundry User と Cognitive Services OpenAI User。azd で定義したエージェントの確認は、scratchpad に `azd ai agent init` で作った別の azd プロジェクトで行った。

## 片付け

```powershell
azd down --purge
```

Entra のアプリ登録も消えます。Foundry のアカウントは `--purge` で論理削除の状態から完全に消します。

## テスト

```powershell
uv run --no-project --with pytest --with-requirements mcp/requirements.txt pytest -q tests
```
