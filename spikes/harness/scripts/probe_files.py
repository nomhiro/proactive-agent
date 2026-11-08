"""確認 4: harness が返したグラフ（Foundry Files）を、エージェント以外の ID（ここでは自分）で取得できるか。

spike-a の instance_identity にプロジェクトの Foundry User を付けてから（反映に数分かかる）、
グラフを作らせ、応答の中のファイル ID を探して取得する。
"""

import json
import re
import time

from _env import agent_identity, assign_role, azd_env, project_client, save

FOUNDRY_USER = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
PROMPT = (
    "作業環境で pip install numpy scipy matplotlib を実行し、時定数 20ms の一次遅れのステップ応答"
    "（0〜200ms）を matplotlib で PNG に描いてください。その PNG をファイルとして返してください。"
)
FILE_ID = re.compile(r"\b(assistant-[A-Za-z0-9]+|file-[A-Za-z0-9]+)\b")


def main() -> None:
    env = azd_env()
    project = project_client(env)
    ident = agent_identity(project, "spike-a")
    print("role:", assign_role(ident["principal_id"], FOUNDRY_USER, env["FOUNDRY_PROJECT_ID"]))

    agent_openai = project.get_openai_client(agent_name="spike-a")
    conv = agent_openai.conversations.create()
    started = time.monotonic()
    resp = agent_openai.responses.create(conversation=conv.id, input=PROMPT, background=True)
    deadline = time.monotonic() + 600
    while resp.status in ("queued", "in_progress") and time.monotonic() < deadline:
        time.sleep(10)
        resp = agent_openai.responses.retrieve(resp.id)
        print(f"{time.monotonic() - started:.0f}s {resp.status}", flush=True)
    raw = resp.model_dump()
    text = json.dumps(raw, ensure_ascii=False, default=str)
    file_ids = sorted(set(FILE_ID.findall(text)))
    result = {"status": resp.status, "elapsed_s": round(time.monotonic() - started, 1),
              "output_types": [o.get("type") for o in raw.get("output", [])], "file_ids": file_ids,
              "output_text": getattr(resp, "output_text", None), "downloads": {}}

    project_openai = project.get_openai_client()
    for fid in file_ids:
        for label, client in (("project", project_openai), ("agent", agent_openai)):
            try:
                data = client.files.content(fid).read()
                result["downloads"][f"{fid}@{label}"] = {"bytes": len(data), "png": data[:4] == b"\x89PNG"}
            except Exception as e:  # noqa: BLE001
                result["downloads"][f"{fid}@{label}"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    result["ok"] = any(d.get("png") for d in result["downloads"].values())
    result["raw_output"] = raw.get("output")
    save("files", result)
    print(json.dumps({k: v for k, v in result.items() if k != "raw_output"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
