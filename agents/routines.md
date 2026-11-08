# 朝の Routines の指示文

毎朝 8:00（日本時間）に Foundry Routines が送る指示文。見出しの `## team` は3チームのアシスタント用、`## chief_engineer` は車種統括エージェント用である。デプロイのフックがこのファイルを読む。

## team

朝のまとめの時刻です。次の順に進めてください。

1. 最初に `begin_morning_digest` を呼ぶ。already_done が true なら、今日のまとめは済んでいるので、何もせずに終える。false なら、返った run_id が今日のまとめの作業記録になる
2. `get_now` で今日の日付を確かめる
3. 次を集める
   - 昨日からの変化: `list_notifications` で、前回のまとめ以降に記録した通知（分類が digest のもの）
   - 今日の期限と予定: `list_schedules`
   - 遅れている作業と進行中の作業: `list_runs`
   - 承認待ちの下書き: `list_proposals`（status は pending）
   - チームの好み: `recall`
4. 3〜5行にまとめて `post_message` でチームに書く。急ぐものを先に書き、データの ID を添える。伝えることがなければ「特になし」と短く書く
5. 最後に `finish_run` を、手順1で返った run_id と、書いた内容の要約で呼ぶ

## chief_engineer

朝の車種ブリーフィングの時刻です。次の順に進めてください。

1. 最初に `begin_morning_digest` を呼ぶ。already_done が true なら、今日のブリーフィングは済んでいるので、何もせずに終える。false なら、返った run_id が今日のブリーフィングの作業記録になる
2. `get_now` で今日の日付を確かめる
3. 全チームの分を集める（team を指定しないと全チーム分が返る）
   - リリースに響くリスク: `list_notifications`、次の統合リリースの `get_release_gaps`
   - 判断が必要なこと: `list_mail` の escalation と、決着していないスレッド
   - 昨日からの変化: `list_notifications`、`list_runs`
4. 「リリースに響くリスク」「判断が必要なこと」「昨日からの変化」の3点に絞って `post_message` で書く。各点は2〜3行までにし、データの ID を添える
5. 最後に `finish_run` を、手順1で返った run_id と、書いた内容の要約で呼ぶ
