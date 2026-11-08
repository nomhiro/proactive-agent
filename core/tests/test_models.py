from datetime import datetime

import pytest
from pydantic import ValidationError

from vehicle_core.constants import AGENT_TEAMS, JST, Team
from vehicle_core.models import Artifact, ChangeEvent, FieldChange, TeamSettings


def test_change_event_editorial_only_is_not_substantive():
    ev = ChangeEvent(id="e1", artifact_id="SPEC-BRK-04", changed_by="tanaka",
                     changed_at=datetime(2026, 11, 18, 14, 0, tzinfo=JST),
                     changes=[FieldChange(path="description", before="a", after="b")])
    assert ev.is_substantive is False


def test_change_event_attribute_change_is_substantive():
    ev = ChangeEvent(id="e2", artifact_id="SIG-BrkPedalPos", changed_by="tanaka",
                     changed_at=datetime(2026, 11, 17, 21, 10, tzinfo=JST),
                     changes=[FieldChange(path="attributes.period_ms", before=10, after=20)])
    assert ev.is_substantive is True


def test_models_reject_naive_datetime():
    with pytest.raises(ValidationError):
        Artifact(id="X", type="requirement", team="integrated_control", title="t",
                 owner="tanaka", updated_at=datetime(2026, 11, 1))


def test_artifact_json_roundtrip_keeps_vehicle_id():
    a = Artifact(id="REQ-112", type="requirement", team="integrated_control", title="回生協調",
                 owner="tanaka", updated_at=datetime(2026, 11, 1, tzinfo=JST))
    d = a.model_dump(mode="json")
    assert d["vehicle_id"] == "kakuu-suv"
    assert Artifact.model_validate(d) == a


def test_agent_teams_are_exactly_four():
    assert AGENT_TEAMS == {Team.CHIEF_ENGINEER, Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL, Team.EVALUATION}


def test_team_settings_agent_client_id_defaults_to_none():
    assert TeamSettings(id="ts-x", team="evaluation").agent_client_id is None
