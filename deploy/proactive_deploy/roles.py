"""エージェント ID へのロール（設計書 7.10 節）。エージェントを作ってからでないと ID がないので、フックで付ける。

ロールの割り当ては azure-mgmt-authorization で行う（az CLI に JSON を渡さない）。名前は grant から決まるので、
何度実行しても同じ割り当てになる。
"""

import uuid

from azure.core.exceptions import HttpResponseError
from pydantic import BaseModel
from vehicle_core.constants import Team

from .definitions import AskMode

# ロールは名前の変更中のため GUID で指定する
FOUNDRY_USER = "53ca6127-db72-4b80-b1b0-d745d6d5456d"  # ファイルの受け渡し（Foundry Files）に要る
AGENT_CONSUMER = "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"  # Foundry Agent Consumer。A2A で呼ぶ側に要る


class RoleGrant(BaseModel):
    principal_id: str
    role_definition_id: str  # ロールの GUID
    scope: str


def role_grants(project_id: str, identities: dict[Team, str], ask_mode: AskMode) -> list[RoleGrant]:
    """identities は、チーム → エージェントの instance_identity の principal ID。"""
    grants = [RoleGrant(principal_id=p, role_definition_id=FOUNDRY_USER, scope=project_id)
              for _, p in sorted(identities.items(), key=lambda kv: kv[0].value)]
    if ask_mode == "a2a" and Team.CHIEF_ENGINEER in identities:
        grants.append(RoleGrant(principal_id=identities[Team.CHIEF_ENGINEER], role_definition_id=AGENT_CONSUMER,
                                scope=project_id))
    return grants


def assignment_name(grant: RoleGrant) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{grant.scope}|{grant.principal_id}|{grant.role_definition_id}"))


def _role_definition_path(grant: RoleGrant) -> str:
    parts = grant.scope.strip("/").split("/")
    subscription = parts[parts.index("subscriptions") + 1]
    return f"/subscriptions/{subscription}/providers/Microsoft.Authorization/roleDefinitions/{grant.role_definition_id}"


def apply_grants(client, grants: list[RoleGrant]) -> list[str]:
    """client は AuthorizationManagementClient。既にある割り当ては成功として扱う。"""
    from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

    names = []
    for g in grants:
        name = assignment_name(g)
        params = RoleAssignmentCreateParameters(role_definition_id=_role_definition_path(g), principal_id=g.principal_id,
                                                principal_type="ServicePrincipal")
        try:
            client.role_assignments.create(scope=g.scope, role_assignment_name=name, parameters=params)
        except HttpResponseError as e:
            if getattr(getattr(e, "error", None), "code", None) != "RoleAssignmentExists":
                raise
        names.append(name)
    return names
