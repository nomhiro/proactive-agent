---
name: analysis
description: 作業環境で HILS のログや回生協調の簡易モデルを解析し、結果の数値とグラフを返す手順。
---

# 作業環境での解析

作業環境は Python 3.13 で、numpy などは最初は入っていない。外への通信は PyPI だけが許されている。

## 手順

1. 最初に、シェルで `pip install numpy scipy matplotlib` を実行する
2. HILS のログが要るときは、`get_test_log` で試験結果 ID を渡して CSV のテキストを得て、作業環境のファイル（例: `logs/<試験結果 ID>.csv`）に書く。truncated が true なら、ログが途中で切れていることを結果に書き添える
3. 信号の周期と回生の応答の遅れを確かめるときは、このスキルの末尾にある回生協調の簡易モデルを、作業環境の regen_model.py に書いて使う。`step_delay_ms(周期)` が遅れ（ms）を返す。変更前と変更後の周期で呼び、差を求める
4. 結果のグラフを matplotlib で PNG に描く。題名、軸の名前と単位、凡例を付ける。日本語のフォントがないことがあるので、グラフの中の文字は英語にする
5. PNG を `upload_file_from_workspace_to_foundry_project` で Foundry にアップロードする。返った file_id を `foundry-file:<file_id>` の形で、`post_message` の attachments か、`send_mail` の本文に入れる

## 結果の書き方

- 結論を先に、数値と単位で書く（例: 「周期を 10ms から 20ms にすると、回生トルクの立ち上がりが約 15ms 遅れる」）
- 使ったモデルと前提（時定数、何を遅れとしたか）を書く
- 簡易モデルの結果であり、実機の値ではないことを書き添える

## 使わないもの

- python-control は使わない。一次遅れのモデルは scipy で書ける
- 作業環境の `date` などの時計は使わない。時刻は `get_now` で得る
- Web からデータを取りに行かない

## 回生協調の簡易モデル（regen_model.py）

デプロイのときに、この下にモデルのコードが付く。そのまま作業環境の regen_model.py に書く。
