"""spike 6 用: harness 付きエージェントを人の操作なしで起動し、結果を dict で返す。

手元（az login の利用者）からも、Functions（マネージド ID）からも同じ関数を呼ぶ。
mode="sync" は応答を待つ。mode="background" は background=True で投げて状態を見に行く。
"""

import time
from typing import Literal

from azure.ai.projects import AIProjectClient

TERMINAL = {"completed", "failed", "cancelled", "incomplete"}


def _summary(response, started: float) -> dict:
    return {
        "status": getattr(response, "status", None),
        "elapsed_s": round(time.monotonic() - started, 1),
        "output_types": [getattr(o, "type", "?") for o in (getattr(response, "output", None) or [])],
        "output_text": (getattr(response, "output_text", "") or "")[:4000],
        "error": str(getattr(response, "error", None) or "") or None,
    }


def run_probe(project_endpoint: str, agent_name: str, prompt: str, mode: Literal["sync", "background"], credential,
              timeout_s: int = 900, poll_s: float = 3.0) -> dict:
    out: dict = {"agent": agent_name, "mode": mode}
    started = time.monotonic()
    try:
        project = AIProjectClient(endpoint=project_endpoint, credential=credential, allow_preview=True)
        openai = project.get_openai_client(agent_name=agent_name)
        conversation = openai.conversations.create()
        out["conversation_id"] = conversation.id
        if mode == "sync":
            response = openai.responses.create(conversation=conversation.id, input=prompt)
        else:
            response = openai.responses.create(conversation=conversation.id, input=prompt, background=True)
            out["accepted_status"] = response.status
            while response.status not in TERMINAL and time.monotonic() - started < timeout_s:
                time.sleep(poll_s)
                response = openai.responses.retrieve(response.id)
        out.update(_summary(response, started))
    except Exception as e:  # spike なので、何で失敗したかをそのまま記録する
        out.update({"status": "exception", "elapsed_s": round(time.monotonic() - started, 1),
                    "error": f"{type(e).__name__}: {str(e)[:2000]}"})
    return out
