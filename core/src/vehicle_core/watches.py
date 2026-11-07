"""チームが頼んだ見張り（データの変更、試験の連続失敗）に合うかを判定する。"""

from collections.abc import Iterable

from .impact import ImpactResult
from .models import TestRun, Watch, WatchKind


def match_change_watches(watches: Iterable[Watch], impact: ImpactResult) -> list[Watch]:
    touched = {impact.origin_id, *impact.impacted_ids}
    return [
        w for w in watches
        if w.kind == WatchKind.ARTIFACT_CHANGED and touched & set(w.target_ids)
    ]


def failure_streak(runs: Iterable[TestRun], feature: str) -> int:
    """その機能の試験結果を新しい順に見て、fail が続く数。"""
    streak = 0
    for r in sorted((r for r in runs if r.feature == feature), key=lambda r: r.executed_at, reverse=True):
        if r.result != "fail":
            break
        streak += 1
    return streak


def match_test_watches(watches: Iterable[Watch], runs: Iterable[TestRun], new_run: TestRun) -> list[Watch]:
    """連続失敗の数が見張りの設定値にちょうど達したものだけを返す（それ以降は鳴らさない）。"""
    all_runs = {r.id: r for r in runs}
    all_runs[new_run.id] = new_run
    # 遅れて届いた古い結果では鳴らさない（連続回数が変わっていないのに二度鳴るのを防ぐ）
    if any(r.feature == new_run.feature and r.executed_at > new_run.executed_at for r in all_runs.values()):
        return []
    streak = failure_streak(all_runs.values(), new_run.feature)
    return [
        w for w in watches
        if w.kind == WatchKind.TEST_FAILURE_STREAK and w.feature == new_run.feature and streak == w.streak
    ]
