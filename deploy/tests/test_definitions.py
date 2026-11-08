from pathlib import Path

from vehicle_core.constants import Team

from proactive_deploy.definitions import (
    a2a_connection_body,
    agent_specs,
    egress_policy_body,
    routine_specs,
    skill_specs,
)

AGENTS = Path(__file__).resolve().parents[2] / "agents"
NAMES = {"asst-chief-engineer", "asst-integrated-control", "asst-motor-control", "asst-evaluation"}


def test_agent_specs_cover_four_teams_with_all_tools():
    specs = agent_specs(AGENTS, ["get_now", "post_message"], "mail")
    assert {s.name for s in specs} == NAMES
    assert all(s.mcp_allowed_tools == ["get_now", "post_message"] for s in specs)
    by_team = {s.team: s for s in specs}
    assert "車両統合制御" in by_team[Team.INTEGRATED_CONTROL].instructions
    assert all(sorted(s.skills) == ["analysis", "drafting", "investigate", "notify-decision"] for s in specs)


def test_only_chief_gets_a2a_targets_in_a2a_mode():
    specs = {s.team: s for s in agent_specs(AGENTS, ["get_now"], "a2a")}
    assert sorted(specs[Team.CHIEF_ENGINEER].a2a_targets) == sorted(NAMES - {"asst-chief-engineer"})
    assert all(not s.a2a_targets for t, s in specs.items() if t != Team.CHIEF_ENGINEER)
    assert all(not s.a2a_targets for s in agent_specs(AGENTS, ["get_now"], "mail"))


def test_skill_specs_read_frontmatter_and_body():
    skills = {s.name: s for s in skill_specs(AGENTS)}
    assert set(skills) == {"analysis", "drafting", "investigate", "notify-decision"}
    assert skills["investigate"].description.startswith("変更、試験結果")
    assert not skills["investigate"].instructions.startswith("---")
    assert "get_now" in skills["investigate"].instructions


def test_analysis_skill_carries_regen_model_code():  # 設計書 7.6 節「モデルのコードはスキルに含めて渡す」
    analysis = next(s for s in skill_specs(AGENTS) if s.name == "analysis")
    assert "def step_delay_ms(" in analysis.instructions
    assert analysis.instructions.rstrip().endswith("```")


def test_routine_specs_use_tokyo_8am_and_stable_names():
    specs = {r.agent_name: r for r in routine_specs(AGENTS)}
    assert set(specs) == NAMES
    for name, r in specs.items():
        assert r.name == f"morning-{name}"
        assert r.cron == "0 8 * * *" and r.time_zone == "Asia/Tokyo"
        assert "begin_morning_digest" in r.input
    assert "車種ブリーフィング" in specs["asst-chief-engineer"].input
    assert "朝のまとめ" in specs["asst-motor-control"].input
    assert "## " not in specs["asst-motor-control"].input


def test_egress_policy_allows_only_pypi():
    body = egress_policy_body()
    egress = body["properties"]["egressPolicy"]
    assert egress["defaultAction"] == "Deny"
    assert {r["match"]["host"] for r in egress["rules"]} == {"pypi.org", "files.pythonhosted.org"}


def test_a2a_connection_targets_agent_endpoint_with_agent_identity():
    body = a2a_connection_body("https://aif-x.services.ai.azure.com/api/projects/proj-proactive", "asst-evaluation")
    p = body["properties"]
    assert p["category"] == "RemoteA2A" and p["authType"] == "AgenticIdentityToken"
    assert p["audience"] == "https://ai.azure.com"
    assert p["target"] == ("https://aif-x.services.ai.azure.com/api/projects/proj-proactive"
                           "/agents/asst-evaluation/endpoint/protocols/a2a")
