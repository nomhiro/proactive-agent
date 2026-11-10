"""誰として見るか（設計書 5.2 節）。田中・佐藤・鈴木・高橋の4人。人物はシードの架空の人物から作る。"""

from dataclasses import dataclass

from fastapi import HTTPException
from vehicle_core.constants import TEAM_LABELS_JA, Team
from vehicle_core.seed import build_dataset

PERSONA_IDS: tuple[str, ...] = ("tanaka", "sato", "suzuki", "takahashi")


@dataclass(frozen=True)
class Persona:
    id: str
    name_ja: str
    team: Team
    role: str

    @property
    def team_label(self) -> str:
        return TEAM_LABELS_JA[self.team]

    def as_dict(self) -> dict:
        return {"id": self.id, "name_ja": self.name_ja, "team": self.team.value, "team_label": self.team_label,
                "role": self.role}


def _personas() -> dict[str, Persona]:
    people = {p.id: p for p in build_dataset().people}
    return {i: Persona(id=i, name_ja=people[i].name_ja, team=people[i].team, role=people[i].role)
            for i in PERSONA_IDS}


PERSONAS: dict[str, Persona] = _personas()


def persona_or_400(persona_id: str | None) -> Persona:
    if persona_id not in PERSONAS:
        raise HTTPException(status_code=400, detail="知らない人物です")
    return PERSONAS[persona_id]
