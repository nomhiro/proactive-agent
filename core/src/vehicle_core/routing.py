"""データの変更や試験結果から、どのチームのアシスタントに調査を頼むかを決める。

影響を受けるだけのチームには頼まない。頼むのは、変更されたデータを持つチームと、
その変更に合う見張りを持つチームだけ（計画の決定1）。
"""

import hashlib
from collections.abc import Iterable
from typing import Literal

from pydantic import AwareDatetime, BaseModel

from .constants import AGENT_TEAMS, DEBOUNCE_WINDOW, VEHICLE_ID, Team
from .impact import Graph, ImpactResult, analyze_impact
from .models import ChangeEvent, Classification, TestRun, Watch
from .notify_policy import final_classification, floor_classification
from .watches import match_change_watches, match_test_watches


class InvestigationRequest(BaseModel):
    id: str  # 冪等キー
    vehicle_id: str = VEHICLE_ID
    team: Team
    trigger: Literal["change", "test_run", "schedule", "mail"]
    origin_artifact_id: str | None
    source_ids: list[str]
    impact: ImpactResult | None
    matched_watch_ids: list[str]
    floor: Classification
    not_before: AwareDatetime


def idempotency_key(team: Team, trigger: str, source_ids: Iterable[str]) -> str:
    raw = f"{team}|{trigger}|{','.join(sorted(set(source_ids)))}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _requests(
    owner_team: Team | None,
    matched: list[Watch],
    *,
    trigger: Literal["change", "test_run"],
    origin_artifact_id: str,
    source_id: str,
    impact: ImpactResult | None,
    substantive: bool,
    not_before,
) -> list[InvestigationRequest]:
    teams = {w.team for w in matched}
    if owner_team is not None:
        teams.add(owner_team)
    out = []
    for team in sorted(t for t in teams if t in AGENT_TEAMS):
        mine = [w for w in matched if w.team == team]
        out.append(InvestigationRequest(
            id=idempotency_key(team, trigger, [source_id]),
            team=team,
            trigger=trigger,
            origin_artifact_id=origin_artifact_id,
            source_ids=[source_id],
            impact=impact,
            matched_watch_ids=sorted(w.id for w in mine),
            floor=floor_classification(impact, substantive, mine),
            not_before=not_before,
        ))
    return out


def route_change(event: ChangeEvent, graph: Graph, watches: Iterable[Watch]) -> list[InvestigationRequest]:
    if not graph.has(event.artifact_id):
        return []
    impact = analyze_impact(graph, event.artifact_id)
    return _requests(
        graph.get(event.artifact_id).team,
        match_change_watches(watches, impact),
        trigger="change",
        origin_artifact_id=event.artifact_id,
        source_id=event.id,
        impact=impact,
        substantive=event.is_substantive,
        not_before=event.changed_at + DEBOUNCE_WINDOW,
    )


def route_test_run(
    new_run: TestRun, runs: Iterable[TestRun], graph: Graph, watches: Iterable[Watch]
) -> list[InvestigationRequest]:
    matched = match_test_watches(watches, runs, new_run)
    if new_run.result == "pass" and not matched:
        return []
    owner = graph.domain_team(new_run.testcase_id) if graph.has(new_run.testcase_id) else None
    return _requests(
        owner,
        matched,
        trigger="test_run",
        origin_artifact_id=new_run.testcase_id,
        source_id=new_run.id,
        impact=None,
        substantive=False,
        not_before=new_run.executed_at,
    )


def coalesce(pending: Iterable[InvestigationRequest]) -> list[InvestigationRequest]:
    """同じチーム・同じデータへの変更で、間隔が DEBOUNCE_WINDOW 以内に連なるものを1件にまとめる。"""
    others: list[InvestigationRequest] = []
    groups: dict[tuple[Team, str | None], list[InvestigationRequest]] = {}
    for r in pending:
        if r.trigger == "change":
            groups.setdefault((r.team, r.origin_artifact_id), []).append(r)
        else:
            others.append(r)

    merged: list[InvestigationRequest] = []
    for reqs in groups.values():
        reqs.sort(key=lambda r: r.not_before)
        run = [reqs[0]]
        for r in reqs[1:]:
            if r.not_before - run[-1].not_before <= DEBOUNCE_WINDOW:
                run.append(r)
            else:
                merged.append(_merge(run))
                run = [r]
        merged.append(_merge(run))
    return merged + others


def _merge(run: list[InvestigationRequest]) -> InvestigationRequest:
    if len(run) == 1:
        return run[0]
    latest = run[-1]
    source_ids = sorted({s for r in run for s in r.source_ids})
    floor = run[0].floor
    for r in run[1:]:
        floor = final_classification(floor, r.floor)
    return latest.model_copy(update={
        "id": idempotency_key(latest.team, latest.trigger, source_ids),
        "source_ids": source_ids,
        "matched_watch_ids": sorted({w for r in run for w in r.matched_watch_ids}),
        "floor": floor,
    })
