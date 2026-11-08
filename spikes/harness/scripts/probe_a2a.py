"""確認 8: harness 付きエージェント（spike-b）で受け側の A2A を有効にし、spike-chief から A2A の道具で呼べるか。"""

import json

from _env import AZD, ROOT, agent_identity, arm, assign_role, azd_env, project_client, save
from probe import WHOAMI_PROMPT  # noqa: F401  （spike-b 側の指示文はそのまま使う）
from spike_invoke import run_probe

AGENT_CONSUMER = "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
CONNECTION = "spike-a2a-b"
CHIEF = "spike-chief"
PROMPT = "A2A の道具で spike-b に「whoami ツールを1回呼び、返ってきた JSON をそのまま返して」と頼み、返事をそのまま出力してください。"


def main() -> None:
    from azure.ai.projects.models import (
        A2AProtocolConfiguration, A2AProtocolVersion, A2ATool, AgentCard, AgentCardSkill, AgentEndpointConfig,
        MicrosoftCopilotHarness, PromptAgentDefinition, ProtocolConfiguration, ResponsesProtocolConfiguration,
    )

    env = azd_env()
    project = project_client(env)
    out: dict = {}
    project.agents.update_details(
        agent_name="spike-b",
        agent_endpoint=AgentEndpointConfig(protocol_configuration=ProtocolConfiguration(
            responses=ResponsesProtocolConfiguration(), a2a=A2AProtocolConfiguration())),
        agent_card=AgentCard(version="1.0", description="確認用。頼まれたとおりに whoami を呼ぶ",
                             skills=[AgentCardSkill(id="whoami", name="whoami", description="whoami を呼んで返す")]))
    details = project.agents.get("spike-b").as_dict()
    out["spike_b_endpoint"] = details.get("agent_endpoint")
    base_url = f"{env['FOUNDRY_PROJECT_ENDPOINT']}/agents/spike-b/endpoint/protocols/a2a"

    conn_url = (f"https://management.azure.com{env['FOUNDRY_PROJECT_ID']}/connections/{CONNECTION}"
                "?api-version=2025-04-01-preview")
    out["connection"] = arm("PUT", conn_url, {"properties": {
        "authType": "AgenticIdentityToken", "category": "RemoteA2A", "target": base_url,
        "audience": "https://ai.azure.com", "credentials": {}, "metadata": {}}})
    conn = project.connections.get(CONNECTION)

    project.agents.create_version(agent_name=CHIEF, definition=PromptAgentDefinition(
        model=env["MODEL_DEPLOYMENT"], harness=MicrosoftCopilotHarness(),
        instructions="あなたは確認用の統括エージェントです。頼まれたとおりに A2A の道具を使い、返事は要約せずにそのまま返してください。",
        tools=[A2ATool(a2a_version=A2AProtocolVersion.V1_0, project_connection_id=conn.id)]))
    ident = agent_identity(project, CHIEF)
    out["chief_identity"] = ident
    out["role"] = assign_role(ident["principal_id"], AGENT_CONSUMER, env["FOUNDRY_PROJECT_ID"])
    print("role assigned; waiting 5 minutes for propagation")
    import time
    time.sleep(300)

    from azure.identity import DefaultAzureCredential
    r = run_probe(env["FOUNDRY_PROJECT_ENDPOINT"], CHIEF, PROMPT, "background", DefaultAzureCredential())
    out["invoke"] = r
    spike_b_oid = agent_identity(project, "spike-b").get("principal_id", "")
    out["ok"] = bool(spike_b_oid) and spike_b_oid in (r.get("output_text") or "")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str)[:5000])
    save("a2a", out)


if __name__ == "__main__":
    main()
