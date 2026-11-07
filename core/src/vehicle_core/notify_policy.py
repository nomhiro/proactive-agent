"""知らせ方の下限（コアで決める）と、いつ届けるかの判定。

LLM の判定は下限より上げることはできるが、下げることはできない。
"""

from collections.abc import Iterable
from datetime import datetime, time, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel

from .clock import to_jst
from .constants import DIGEST_TIME
from .impact import ImpactResult
from .models import Classification, DeliveryMode, Proactivity, TeamSettings, Watch

_RANK = {Classification.SILENT: 0, Classification.DIGEST: 1, Classification.NOTIFY_NOW: 2}


def floor_classification(
    impact: ImpactResult | None, substantive: bool, matched: Iterable[Watch]
) -> Classification:
    matched = list(matched)
    if substantive and impact is not None and (impact.touches_safety or impact.affects_release_ids):
        return Classification.NOTIFY_NOW
    if any(w.delivery == DeliveryMode.IMMEDIATE for w in matched):
        return Classification.NOTIFY_NOW
    if any(w.delivery == DeliveryMode.DIGEST for w in matched):
        return Classification.DIGEST
    return Classification.SILENT


def final_classification(floor: Classification, llm: Classification) -> Classification:
    return max(floor, llm, key=_RANK.__getitem__)


def is_quiet(now: datetime, settings: TeamSettings) -> bool:
    t = to_jst(now).time()
    start, end = settings.quiet_start, settings.quiet_end
    if start <= end:  # 日をまたがない時間帯
        return start <= t < end
    return t >= start or t < end


def next_time_at(now: datetime, t: time) -> datetime:
    """now 以降で最初の JST の時刻 t（now がちょうど t なら now）。"""
    now = to_jst(now)
    candidate = now.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=t.microsecond)
    if candidate < now:
        candidate += timedelta(days=1)
    return candidate


class DeliveryDecision(BaseModel):
    mode: Literal["immediate", "digest", "none"]
    deliver_at: AwareDatetime | None


def decide_delivery(
    classification: Classification, touches_safety: bool, now: datetime, settings: TeamSettings
) -> DeliveryDecision:
    now = to_jst(now)
    if touches_safety:
        return DeliveryDecision(mode="immediate", deliver_at=now)
    if settings.proactivity == Proactivity.OFF or classification == Classification.SILENT:
        return DeliveryDecision(mode="none", deliver_at=None)
    if classification == Classification.DIGEST:
        if settings.proactivity == Proactivity.IMPORTANT_ONLY:
            return DeliveryDecision(mode="none", deliver_at=None)
        if settings.proactivity != Proactivity.FREQUENT:
            return DeliveryDecision(mode="digest", deliver_at=next_time_at(now, DIGEST_TIME))
    # notify_now（または frequent の digest）
    if is_quiet(now, settings):
        return DeliveryDecision(mode="immediate", deliver_at=next_time_at(now, settings.quiet_end))
    return DeliveryDecision(mode="immediate", deliver_at=now)
