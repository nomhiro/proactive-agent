"""agents/ のファイルから、エージェント、スキル、Routines、RAI ポリシー、A2A の接続の定義を作る（Azure には触れない）。"""

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from vehicle_core.constants import AGENT_TEAMS, Team, agent_name

AskMode = Literal["a2a", "mail"]

MORNING_CRON = "0 8 * * *"
TIME_ZONE = "Asia/Tokyo"
# 作業環境から外への通信で許すもの（設計書 7.5 節。解析のたびに pip install するため）
PYPI_HOSTS = ("pypi.org", "files.pythonhosted.org")


class SkillSpec(BaseModel):
    name: str
    description: str
    instructions: str


class AgentSpec(BaseModel):
    name: str
    team: Team
    instructions: str
    skills: list[str]
    mcp_allowed_tools: list[str]
    a2a_targets: list[str]


class RoutineSpec(BaseModel):
    name: str
    agent_name: str
    cron: str
    time_zone: str
    input: str


def _teams() -> list[Team]:
    return sorted(AGENT_TEAMS, key=lambda t: t.value)


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not m:
        raise ValueError("SKILL.md に frontmatter がありません")
    meta = {k.strip(): v.strip() for k, v in (ln.split(":", 1) for ln in m.group(1).splitlines() if ":" in ln)}
    return meta, text[m.end():].strip()


def skill_specs(root: Path) -> list[SkillSpec]:
    """agents/skills/*/SKILL.md。analysis には回生協調の簡易モデルのコードを末尾に付ける（Task 8 の決定）。"""
    out = []
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
        for extra in sorted(path.parent.glob("*.py")):
            body += f"\n\n```python\n# {extra.name}\n{extra.read_text(encoding='utf-8').strip()}\n```"
        out.append(SkillSpec(name=meta["name"], description=meta["description"], instructions=body))
    return out


def agent_specs(root: Path, tool_names: list[str], ask_mode: AskMode) -> list[AgentSpec]:
    skills = [s.name for s in skill_specs(root)]
    names = {t: agent_name(t) for t in _teams()}
    specs = []
    for team in _teams():
        targets = ([n for t, n in names.items() if t != Team.CHIEF_ENGINEER]
                   if ask_mode == "a2a" and team == Team.CHIEF_ENGINEER else [])
        specs.append(AgentSpec(
            name=names[team], team=team,
            instructions=(root / "instructions" / f"{team.value}.md").read_text(encoding="utf-8"),
            skills=skills, mcp_allowed_tools=list(tool_names), a2a_targets=targets,
        ))
    return specs


def _routine_sections(root: Path) -> dict[str, str]:
    text = (root / "routines.md").read_text(encoding="utf-8")
    sections = {}
    for chunk in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, body = chunk.partition("\n")
        sections[title.strip()] = body.strip()
    return sections


def routine_specs(root: Path) -> list[RoutineSpec]:
    """4体それぞれの朝の Routine。名前は morning-<エージェント名>（Functions の FoundryRoutineDispatcher と同じ）。"""
    sections = _routine_sections(root)
    out = []
    for team in _teams():
        name = agent_name(team)
        body = sections["chief_engineer" if team == Team.CHIEF_ENGINEER else "team"]
        out.append(RoutineSpec(name=f"morning-{name}", agent_name=name, cron=MORNING_CRON, time_zone=TIME_ZONE,
                               input=body))
    return out


def egress_policy_body() -> dict:
    """RAI ポリシー（api-version 2026-05-15-preview）。外への通信は PyPI だけを許す。"""
    rules = [{"name": f"allow-{host.split('.')[0]}", "ruleType": "Fqdn", "match": {"host": host},
              "action": {"actionType": "Allow"}} for host in PYPI_HOSTS]
    return {"properties": {"mode": "Blocking", "basePolicyName": "Microsoft.DefaultV2", "contentFilters": [],
                           "egressPolicy": {"mode": "Enforced", "defaultAction": "Deny", "rules": rules}}}


def a2a_connection_body(project_endpoint: str, target_agent: str) -> dict:
    """統括から各チームのアシスタントを A2A で呼ぶための接続（api-version 2025-04-01-preview）。"""
    return {"properties": {
        "authType": "AgenticIdentityToken", "category": "RemoteA2A",
        "target": f"{project_endpoint.rstrip('/')}/agents/{target_agent}/endpoint/protocols/a2a",
        "audience": "https://ai.azure.com", "credentials": {}, "metadata": {},
    }}
