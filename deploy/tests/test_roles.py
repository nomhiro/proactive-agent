from types import SimpleNamespace

import pytest
from azure.core.exceptions import HttpResponseError
from vehicle_core.constants import Team

from proactive_deploy.roles import (
    AGENT_CONSUMER,
    FOUNDRY_USER,
    RoleGrant,
    apply_grants,
    assignment_name,
    role_grants,
)

PROJECT = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/aif/projects/p"
IDS = {Team.CHIEF_ENGINEER: "p-chief", Team.INTEGRATED_CONTROL: "p-ic", Team.MOTOR_CONTROL: "p-mc",
       Team.EVALUATION: "p-ev"}


def test_role_grants_give_foundry_user_to_each_agent():
    grants = role_grants(PROJECT, IDS, "mail")
    assert {(g.principal_id, g.role_definition_id, g.scope) for g in grants} == {
        (p, FOUNDRY_USER, PROJECT) for p in IDS.values()}


def test_role_grants_add_agent_consumer_to_chief_only_in_a2a_mode():
    consumers = [g for g in role_grants(PROJECT, IDS, "a2a") if g.role_definition_id == AGENT_CONSUMER]
    assert [g.principal_id for g in consumers] == ["p-chief"]
    assert AGENT_CONSUMER == "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"


def test_assignment_name_is_stable():
    g = RoleGrant(principal_id="p-ic", role_definition_id=FOUNDRY_USER, scope=PROJECT)
    assert assignment_name(g) == assignment_name(g.model_copy())
    assert assignment_name(g) != assignment_name(g.model_copy(update={"principal_id": "p-mc"}))


class FakeAssignments:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.calls = []

    def create(self, scope, role_assignment_name, parameters):
        self.calls.append((scope, role_assignment_name, parameters))
        if role_assignment_name in self.existing:
            err = HttpResponseError(message="The role assignment already exists.")
            err.error = SimpleNamespace(code="RoleAssignmentExists")
            raise err


def test_apply_grants_treats_existing_assignment_as_success():
    grants = role_grants(PROJECT, IDS, "mail")
    fake = FakeAssignments(existing={assignment_name(grants[0])})
    names = apply_grants(SimpleNamespace(role_assignments=fake), grants)
    assert names == [assignment_name(g) for g in grants]
    scope, _, params = fake.calls[1]
    assert scope == PROJECT
    assert params.role_definition_id == (
        f"/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/{FOUNDRY_USER}")
    assert params.principal_type == "ServicePrincipal"


def test_apply_grants_raises_other_errors():
    class Broken(FakeAssignments):
        def create(self, scope, role_assignment_name, parameters):
            raise HttpResponseError(message="Forbidden")
    with pytest.raises(HttpResponseError):
        apply_grants(SimpleNamespace(role_assignments=Broken()), role_grants(PROJECT, IDS, "mail"))
