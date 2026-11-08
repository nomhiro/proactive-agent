import pytest

from vehicle_core.constants import Team, agent_name


def test_agent_name_uses_hyphenated_team():
    assert agent_name(Team.INTEGRATED_CONTROL) == "asst-integrated-control"
    assert agent_name(Team.CHIEF_ENGINEER) == "asst-chief-engineer"


def test_agent_name_rejects_team_without_assistant():
    with pytest.raises(ValueError):
        agent_name(Team.BATTERY_CONTROL)
