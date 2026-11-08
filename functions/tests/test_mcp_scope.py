import pytest
from vehicle_core.constants import Team

from proactive_functions.mcp.context import ToolError
from proactive_functions.mcp.scope import effective_team, read_scope


def test_scope_table_matches_spec():
    # 設計書 7.5 節の表
    for c in ("artifacts", "change_events", "test_runs"):
        assert read_scope(c) == "all"
    for c in ("notifications", "proposals", "agent_runs", "schedules", "agent_mail"):
        assert read_scope(c) == "own_or_chief"
    for c in ("messages", "watches", "investigations"):
        assert read_scope(c) == "own"
    assert read_scope("team_settings") == "members"


def test_unknown_container_has_no_scope():
    with pytest.raises(KeyError):
        read_scope("leases")


def test_non_chief_always_gets_own_team():
    assert effective_team(Team.INTEGRATED_CONTROL, "motor_control") == Team.INTEGRATED_CONTROL
    assert effective_team(Team.INTEGRATED_CONTROL, None) == Team.INTEGRATED_CONTROL


def test_chief_can_pick_a_team_or_all():
    assert effective_team(Team.CHIEF_ENGINEER, "motor_control") == Team.MOTOR_CONTROL
    assert effective_team(Team.CHIEF_ENGINEER, None) is None


def test_chief_unknown_team_is_tool_error():
    with pytest.raises(ToolError):
        effective_team(Team.CHIEF_ENGINEER, "nope")
