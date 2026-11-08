"""azd の postdeploy フック。Bicep では作れないもの、エージェントができてからでないと作れないものを作る（設計書 7.10 節）。

順番（どの段も何度実行してもよい）:
1. MCP 接続（agentic-identity）
2. RAI ポリシー（外への通信は PyPI だけ）
3. スキル4つ
4. エージェント4体（3チームを先に作って A2A を公開し、A2A の接続を作ってから統括を作る）
5. エージェント ID へのロール
6. team_settings.agent_client_id（MCP サーバーが呼び出し元のチームを決める対応表）
7. Memory ストア
8. 朝の Routines

エージェントを作り直すとエージェント ID が変わるので、5 と 6 は毎回合わせ直す。
"""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from vehicle_core.constants import VEHICLE_ID, Team

from .definitions import (
    AgentSpec,
    a2a_connection_body,
    agent_specs,
    egress_policy_body,
    routine_specs,
    skill_specs,
)
from .roles import apply_grants, role_grants

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "agents"
MCP_CONNECTION = "proactive-mcp"
RAI_POLICY = "proactive-egress-pypi"
ASK_MODE = "a2a"  # Plan 3 決定 15
RAI_API = "2026-05-15-preview"
CONNECTION_API = "2025-04-01-preview"
AGENT_CARDS = {
    Team.INTEGRATED_CONTROL: "車両統合制御チームのアシスタント。アクセル・ブレーキ操作の制御と回生ブレーキの協調制御の状況に答える",
    Team.MOTOR_CONTROL: "モーター制御チームのアシスタント。駆動モーターのトルク制御のモデルと作業の状況に答える",
    Team.EVALUATION: "評価チームのアシスタント。SILS / HILS の試験結果と失敗の傾向に答える",
}


def sync_agent_client_ids(store, identities: dict[Team, str]) -> list[str]:
    """identities は、チーム → エージェントの instance_identity の client ID。変えたチームを返す。"""
    changed = []
    for team, client_id in sorted(identities.items(), key=lambda kv: kv[0].value):
        doc_id = f"ts-{team.value}"
        doc = store.get("team_settings", doc_id)
        if doc is None:
            store.create("team_settings", {"id": doc_id, "vehicle_id": VEHICLE_ID, "team": team.value,
                                           "agent_client_id": client_id})
            changed.append(team.value)
        elif doc.get("agent_client_id") != client_id:
            store.replace("team_settings", doc | {"agent_client_id": client_id}, etag=doc["_etag"])
            changed.append(team.value)
    return changed


# --- Azure を呼ぶ部分（単体テストはしない。Task 11 の確認で通す） -------------------------

def _env(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    out = subprocess.run([shutil.which("azd") or "azd", "env", "get-value", name], capture_output=True, text=True,
                         check=False)
    if out.returncode != 0 or not out.stdout.strip():
        raise SystemExit(f"{name} がわかりません。azd provision を済ませてください")
    return out.stdout.strip()


def _arm_put(credential, url: str, body: dict) -> int:
    token = credential.get_token("https://management.azure.com/.default").token
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="PUT",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ARM PUT {url} → {e.code}: {e.read().decode(errors='replace')[:800]}") from None


def _step(title: str, result) -> None:
    print(f"[setup] {title}: {result}")


def create_mcp_connection(endpoint: str, function_url: str, audience: str) -> None:
    subprocess.run(
        [shutil.which("azd") or "azd", "ai", "connection", "create", MCP_CONNECTION, "--kind", "remote-tool",
         "--target", f"{function_url}/api/mcp", "--auth-type", "agentic-identity", "--audience", audience,
         "--force", "--no-prompt", "-p", endpoint],
        cwd=ROOT, check=True)


def _definition(spec: AgentSpec, *, model: str, mcp_url: str, mcp_connection_id: str, policy_id: str,
                a2a_connection_ids: list[str]):
    from azure.ai.projects.models import (
        A2AProtocolVersion,
        A2ATool,
        MCPTool,
        MicrosoftCopilotHarness,
        MicrosoftCopilotToolsetConfig,
        MicrosoftCopilotToolsetDefaultConfig,
        MicrosoftCopilotToolsetPreview,
        PromptAgentDefinition,
        RaiConfig,
        SkillReference,
    )
    # harness の道具はファイルの読み書きとシェルだけ。Web 取得とサブエージェントは外す（設計書 7.5 節）
    toolset = MicrosoftCopilotToolsetPreview(
        default_config=MicrosoftCopilotToolsetDefaultConfig(enabled=False),
        configs=[MicrosoftCopilotToolsetConfig(name=n, enabled=True)
                 for n in ("filesystem_read", "filesystem_write", "shell")])
    tools = [toolset, MCPTool(server_label="proactive", server_url=mcp_url, project_connection_id=mcp_connection_id,
                              require_approval="never", allowed_tools=spec.mcp_allowed_tools)]
    tools += [A2ATool(a2a_version=A2AProtocolVersion.V1_0, project_connection_id=cid) for cid in a2a_connection_ids]
    return PromptAgentDefinition(
        model=model, instructions=spec.instructions, harness=MicrosoftCopilotHarness(), tools=tools,
        skills=[SkillReference(name=s) for s in spec.skills], rai_config=RaiConfig(rai_policy_name=policy_id))


def _enable_a2a(project, spec: AgentSpec) -> None:
    from azure.ai.projects.models import (
        A2AProtocolConfiguration,
        AgentCard,
        AgentCardSkill,
        AgentEndpointConfig,
        ProtocolConfiguration,
        ResponsesProtocolConfiguration,
    )
    description = AGENT_CARDS[spec.team]
    project.agents.update_details(
        agent_name=spec.name,
        agent_endpoint=AgentEndpointConfig(protocol_configuration=ProtocolConfiguration(
            responses=ResponsesProtocolConfiguration(), a2a=A2AProtocolConfiguration())),
        agent_card=AgentCard(version="1.0", description=description,
                             skills=[AgentCardSkill(id="team-status", name="チームの状況", description=description)]))


def _identity(project, name: str) -> dict:
    ident = project.agents.get(name).as_dict().get("instance_identity") or {}
    if not ident.get("principal_id") or not ident.get("client_id"):
        raise RuntimeError(f"{name} のエージェント ID が読めません: {ident}")
    return ident


def ensure_memory_store(project, name: str, chat_model: str, embedding_model: str) -> str:
    from azure.ai.projects.models import MemoryStoreDefaultDefinition, MemoryStoreDefaultOptions
    try:
        project.beta.memory_stores.get(name)
        return "exists"
    except Exception:  # noqa: BLE001 — ないときの例外の型は版で変わる
        project.beta.memory_stores.create(
            name=name, description="チームの好み（scope はチーム）",
            definition=MemoryStoreDefaultDefinition(
                chat_model=chat_model, embedding_model=embedding_model,
                options=MemoryStoreDefaultOptions(chat_summary_enabled=False, user_profile_enabled=True)))
        return "created"


def main() -> None:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import SkillInlineContent
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.authorization import AuthorizationManagementClient

    from proactive_functions.mcp.server import build_registry
    from proactive_functions.store import CosmosStore

    endpoint = _env("FOUNDRY_PROJECT_ENDPOINT")
    project_id = _env("FOUNDRY_PROJECT_ID")
    account_id = _env("FOUNDRY_ACCOUNT_ID")
    model = _env("MODEL_DEPLOYMENT")
    function_url = _env("FUNCTION_APP_URL")
    credential = DefaultAzureCredential()
    project = AIProjectClient(endpoint=endpoint, credential=credential, allow_preview=True)

    create_mcp_connection(endpoint, function_url, _env("GATEWAY_APP_ID_URI"))
    mcp_connection_id = project.connections.get(MCP_CONNECTION).id
    _step("MCP 接続", mcp_connection_id)

    policy_id = f"{account_id}/raiPolicies/{RAI_POLICY}"
    _step("RAI ポリシー", _arm_put(credential, f"https://management.azure.com{policy_id}?api-version={RAI_API}",
                                   egress_policy_body()))

    for s in skill_specs(AGENTS):
        project.beta.skills.create(s.name, inline_content=SkillInlineContent(description=s.description,
                                                                             instructions=s.instructions),
                                   default=True)
        _step("スキル", s.name)

    tool_names = [t["name"] for t in build_registry().list()]
    specs = agent_specs(AGENTS, tool_names, ASK_MODE)
    common = dict(model=model, mcp_url=f"{function_url}/api/mcp", mcp_connection_id=mcp_connection_id,
                  policy_id=policy_id)
    a2a_ids: dict[str, str] = {}
    for spec in [s for s in specs if not s.a2a_targets]:
        version = project.agents.create_version(agent_name=spec.name,
                                                definition=_definition(spec, a2a_connection_ids=[], **common))
        _step("エージェント", f"{spec.name} v{version.version}")
        if spec.team in AGENT_CARDS:
            _enable_a2a(project, spec)
            conn_name = f"a2a-{spec.name}"
            _arm_put(credential, f"https://management.azure.com{project_id}/connections/{conn_name}"
                                 f"?api-version={CONNECTION_API}", a2a_connection_body(endpoint, spec.name))
            a2a_ids[spec.name] = project.connections.get(conn_name).id
            _step("A2A の接続", conn_name)
    for spec in [s for s in specs if s.a2a_targets]:
        version = project.agents.create_version(agent_name=spec.name, definition=_definition(
            spec, a2a_connection_ids=[a2a_ids[n] for n in spec.a2a_targets], **common))
        _step("エージェント", f"{spec.name} v{version.version}")

    identities = {s.team: _identity(project, s.name) for s in specs}
    subscription = project_id.strip("/").split("/")[1]
    auth = AuthorizationManagementClient(credential, subscription)
    grants = role_grants(project_id, {t: i["principal_id"] for t, i in identities.items()}, ASK_MODE)
    _step("ロール", f"{len(apply_grants(auth, grants))} 件")

    store = CosmosStore(_env("COSMOS_ENDPOINT"), _env("COSMOS_DATABASE"), credential)
    changed = sync_agent_client_ids(store, {t: i["client_id"] for t, i in identities.items()})
    _step("team_settings.agent_client_id", changed or "変更なし")

    _step("Memory ストア", ensure_memory_store(project, _env("MEMORY_STORE_NAME"), model,
                                               _env("EMBEDDING_DEPLOYMENT")))

    for r in routine_specs(AGENTS):
        project.beta.routines.create_or_update(
            routine_name=r.name, description=f"{r.agent_name} の朝のまとめ", enabled=True,
            triggers={"morning": {"type": "schedule", "cron_expression": r.cron, "time_zone": r.time_zone}},
            action={"type": "invoke_agent_responses_api", "agent_name": r.agent_name, "input": r.input})
        _step("Routine", r.name)


if __name__ == "__main__":
    main()
