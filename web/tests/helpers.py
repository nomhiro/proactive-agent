from datetime import datetime

from proactive_functions.memory_store import MemoryStore
from proactive_functions.seeding import seed_store
from vehicle_core.constants import JST, VEHICLE_ID

REAL = datetime(2026, 11, 9, 12, 0, tzinfo=JST)  # 実時間（固定）
NIGHT = datetime(2026, 11, 17, 21, 30, tzinfo=JST)
MORNING = datetime(2026, 11, 18, 8, 5, tzinfo=JST)


def seeded() -> MemoryStore:
    store = MemoryStore()
    seed_store(store, reset=False, system_now=REAL)
    return store


def notification(id_, *, team="integrated_control", delivered_at=None, classification="notify_now",
                 origin="SIG-BrkPedalPos", impacted=None, created_at=NIGHT, **extra) -> dict:
    return {"id": id_, "vehicle_id": VEHICLE_ID, "team": team, "origin_artifact_id": origin,
            "impacted_ids": impacted if impacted is not None else ["MDL-MotorTq"],
            "highlight_ids": [origin, "MDL-MotorTq"] if origin else [], "cross_team_edges": [],
            "classification": classification, "deliver_at": None, "reason": "理由",
            "created_at": created_at.isoformat(),
            "delivered_at": delivered_at.isoformat() if delivered_at else None, **extra}


def message(id_, *, team="integrated_control", created_at=NIGHT, role="assistant", author="agent",
            text="本文", **extra) -> dict:
    return {"id": id_, "vehicle_id": VEHICLE_ID, "team": team, "role": role, "author": author, "text": text,
            "notification_id": None, "proposal_id": None, "attachments": [],
            "created_at": created_at.isoformat(), **extra}


def run(id_, *, team="integrated_control", state="running", started_at=NIGHT, finished_at=None,
        detail=None, title="作業") -> dict:
    return {"id": id_, "vehicle_id": VEHICLE_ID, "team": team, "state": state, "title": title,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat() if finished_at else None, "detail": detail or {}}


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now
