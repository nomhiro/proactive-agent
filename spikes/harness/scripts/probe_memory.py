"""確認 5: Memory ストアを scope＝チームで読み書きできるか（手元の ID と、Functions の ID）。"""

import json

from _env import azd_env, project_client, queue_probe, save
from spike_memory import memory_probe

STORE = "spike-team-memory"


def main() -> None:
    env = azd_env()
    local = {}
    try:
        local = memory_probe(project_client(env), STORE, env["MODEL_DEPLOYMENT"], env["EMBEDDING_DEPLOYMENT"])
    except Exception as e:  # noqa: BLE001
        local = {"error": f"{type(e).__name__}: {e}"}
    print("local:", json.dumps(local, ensure_ascii=False, indent=2))
    remote = queue_probe(env, {"kind": "memory", "store": STORE, "chat_model": env["MODEL_DEPLOYMENT"],
                               "embedding_model": env["EMBEDDING_DEPLOYMENT"]})
    print("functions:", json.dumps(remote, ensure_ascii=False, indent=2))
    save("memory", {"local": local, "functions": remote})


if __name__ == "__main__":
    main()
