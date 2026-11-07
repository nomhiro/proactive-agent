"""リリース前の抜け漏れ（未検証の要求、未完了のレビュー、未検証の安全要求）を数える。"""

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from .models import Artifact, ArtifactType, TestRun
from .seed import Dataset


class ReleaseGapReport(BaseModel):
    release_id: str
    unverified_requirement_ids: list[str]
    open_review_ids: list[str]
    unverified_safety_ids: list[str]


def latest_result(runs: Iterable[TestRun], testcase_id: str) -> Literal["pass", "fail"] | None:
    mine = [r for r in runs if r.testcase_id == testcase_id]
    if not mine:
        return None
    return max(mine, key=lambda r: r.executed_at).result


def release_gaps(dataset: Dataset, release_id: str) -> ReleaseGapReport:
    in_release = [a for a in dataset.artifacts if release_id in a.release_ids]
    tests = [a for a in dataset.artifacts if a.type == ArtifactType.TESTCASE]
    runs = list(dataset.test_runs)

    def verified(target: Artifact) -> bool:
        return any(target.id in t.links and latest_result(runs, t.id) == "pass" for t in tests)

    def unverified_of(type_: ArtifactType) -> list[str]:
        return sorted(a.id for a in in_release if a.type == type_ and not verified(a))

    return ReleaseGapReport(
        release_id=release_id,
        unverified_requirement_ids=unverified_of(ArtifactType.REQUIREMENT),
        open_review_ids=sorted(
            a.id for a in in_release if a.type == ArtifactType.REVIEW and a.status != "closed"
        ),
        unverified_safety_ids=unverified_of(ArtifactType.SAFETY_REQUIREMENT),
    )
