"""MCP 接続（agentic-identity）と、harness 付きエージェント2体（spike-a、spike-b）を作る。

2体とも同じ接続、同じ MCP サーバーを使う。spike 2 では、2体のトークンを区別できるかを見る。
何度実行してもよい（接続は上書き、エージェントは新しい版を作る）。
"""

import json
import subprocess

from _env import AZD, ROOT, azd_env
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, MicrosoftCopilotHarness, PromptAgentDefinition
from azure.identity import DefaultAzureCredential

AGENTS = ("spike-a", "spike-b")
CONNECTION = "spike-mcp"
INSTRUCTIONS = (
    "あなたは確認用のエージェントです。頼まれたとおりに道具を使い、道具の結果は要約せずにそのまま返してください。"
)


def main() -> None:
    env = azd_env()
    endpoint = env["FOUNDRY_PROJECT_ENDPOINT"]
    subprocess.run(
        [AZD, "ai", "connection", "create", CONNECTION, "--kind", "remote-tool", "--target", env["MCP_URL"],
         "--auth-type", "agentic-identity", "--audience", env["MCP_AUDIENCE"], "--force", "--no-prompt",
         "-p", endpoint],
        cwd=ROOT, check=True)

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential(), allow_preview=True)
    connection = project.connections.get(CONNECTION)
    print(f"connection: {connection.id}")
    for name in AGENTS:
        version = project.agents.create_version(
            agent_name=name,
            definition=PromptAgentDefinition(
                model=env["MODEL_DEPLOYMENT"],
                instructions=INSTRUCTIONS,
                harness=MicrosoftCopilotHarness(),
                tools=[MCPTool(server_label="spike", server_url=env["MCP_URL"], project_connection_id=connection.id,
                               require_approval="never", allowed_tools=["whoami"])],
            ),
        )
        details = project.agents.get(name).as_dict()
        print(json.dumps({
            "agent": name,
            "version": version.version,
            "agent_endpoint": details.get("agent_endpoint"),
            "instance_identity": details.get("instance_identity"),
            "blueprint": details.get("blueprint"),
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
