"""Task 1 Step 6・7（SDK での確認）: スキルの添付、harness の道具の絞り込み、RAI ポリシーの外向き通信の制限。

spike-c を作り、次を1つの会話で順に頼む:
  1. スキルに書いた合言葉を答える（スキルが読めているか）
  2. pip install numpy（PyPI は許可）
  3. curl https://example.com（許可していないので止まるはず）
  4. Web 取得の道具で https://example.com を読む（道具を外したので使えないはず）
"""

import json
import time

from _env import arm, azd_env, project_client, save

SKILL = "spike-passphrase"
POLICY = "spike-egress-pypi"
AGENT = "spike-c"
PASSPHRASE = "あおいとり"
STEPS = [
    "スキル spike-passphrase に書かれている合言葉を答えてください。",
    "シェルで pip install numpy を実行し、最後の2行をそのまま返してください。",
    "シェルで curl -sS -m 15 -o /dev/null -w '%{http_code}' https://example.com を実行し、出力かエラーをそのまま返してください。",
    "Web 取得の道具で https://example.com を読み、タイトルを返してください。道具が使えなければ、使えないと答えてください。",
]


def main() -> None:
    from azure.ai.projects.models import (
        MCPTool, MicrosoftCopilotHarness, MicrosoftCopilotToolsetConfig, MicrosoftCopilotToolsetDefaultConfig,
        MicrosoftCopilotToolsetPreview, PromptAgentDefinition, RaiConfig, SkillInlineContent, SkillReference,
    )

    env = azd_env()
    project = project_client(env)
    out: dict = {}

    try:
        skill = project.beta.skills.create(name=SKILL, inline_content=SkillInlineContent(
            description="確認用。合言葉を聞かれたときに使う",
            instructions=f"合言葉を聞かれたら「{PASSPHRASE}」と答える。"))
        out["skill"] = skill.as_dict() if hasattr(skill, "as_dict") else str(skill)
    except Exception as e:  # noqa: BLE001
        out["skill_error"] = f"{type(e).__name__}: {e}"[:600]

    account_id = env["FOUNDRY_PROJECT_ID"].split("/projects/")[0]
    policy_id = f"{account_id}/raiPolicies/{POLICY}"
    out["rai_policy"] = arm("PUT", f"https://management.azure.com{policy_id}?api-version=2026-05-15-preview", {
        "properties": {"mode": "Blocking", "basePolicyName": "Microsoft.DefaultV2", "contentFilters": [],
                       "egressPolicy": {"mode": "Enforced", "defaultAction": "Deny", "rules": [
                           {"name": "allow-pypi", "ruleType": "Fqdn", "match": {"host": "pypi.org"},
                            "action": {"actionType": "Allow"}},
                           {"name": "allow-pythonhosted", "ruleType": "Fqdn",
                            "match": {"host": "files.pythonhosted.org"}, "action": {"actionType": "Allow"}}]}}})
    rai_ok = out["rai_policy"]["status"] in (200, 201)

    conn = project.connections.get("spike-mcp")
    toolset = MicrosoftCopilotToolsetPreview(
        default_config=MicrosoftCopilotToolsetDefaultConfig(enabled=False),
        configs=[MicrosoftCopilotToolsetConfig(name=n, enabled=True)
                 for n in ("filesystem_read", "filesystem_write", "shell")])
    definition = dict(
        model=env["MODEL_DEPLOYMENT"], harness=MicrosoftCopilotHarness(),
        instructions="あなたは確認用のエージェントです。頼まれたとおりに実行し、結果は要約せずに返してください。",
        tools=[toolset, MCPTool(server_label="spike", server_url=env["MCP_URL"], project_connection_id=conn.id,
                                require_approval="never", allowed_tools=["whoami"])],
    )
    if "skill" in out:
        definition["skills"] = [SkillReference(name=SKILL)]
    if rai_ok:
        definition["rai_config"] = RaiConfig(rai_policy_name=policy_id)
    try:
        version = project.agents.create_version(agent_name=AGENT, definition=PromptAgentDefinition(**definition))
        out["agent_version"] = version.version
    except Exception as e:  # noqa: BLE001
        out["agent_error"] = f"{type(e).__name__}: {e}"[:1200]
        save("agent-config", out)
        raise

    client = project.get_openai_client(agent_name=AGENT)
    conv = client.conversations.create()
    answers = []
    for prompt in STEPS:
        resp = client.responses.create(conversation=conv.id, input=prompt, background=True)
        while resp.status in ("queued", "in_progress"):
            time.sleep(5)
            resp = client.responses.retrieve(resp.id)
        raw = resp.model_dump()
        answers.append({"prompt": prompt, "status": resp.status, "text": getattr(resp, "output_text", None),
                        "output_types": [o.get("type") for o in raw.get("output", [])],
                        "error": raw.get("error")})
    out["answers"] = answers
    out["skill_read"] = PASSPHRASE in (answers[0]["text"] or "")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str)[:6000])
    save("agent-config", out)


if __name__ == "__main__":
    main()
