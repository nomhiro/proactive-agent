# proactive-agent

架空の自動車メーカーで新型 EV の制御ソフトウェアを開発している、という設定の PoC です。開発データの変化を見張り、領域をまたぐ影響を調べて、関係するチームとチーフエンジニアに頼まれる前に知らせるエージェントを、Microsoft Foundry（ホステッドエージェント）、Azure Functions、Cosmos DB、Container Apps Sandboxes で作ります。

## 状態

実装中です。いまあるのは、Azure も LLM も使わずに動く判定ロジックと架空データ（`core/`）だけです。

- 設計書: [docs/superpowers/specs/2026-11-07-proactive-vehicle-agent-design.md](docs/superpowers/specs/2026-11-07-proactive-vehicle-agent-design.md)
- 実装計画: [docs/superpowers/plans/](docs/superpowers/plans/)

## 開発

[uv](https://docs.astral.sh/uv/) が必要です。core のテストは次のコマンドで実行します。

```bash
uv run --directory core pytest
```

登場する会社、車種、人物、データはすべて架空のものです。
