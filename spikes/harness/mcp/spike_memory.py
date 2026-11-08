"""確認 5: Memory ストアを scope＝チームで読み書きできるか。手元の ID と Functions の ID の両方から呼ぶ。"""

import time
import uuid


def _texts(items) -> list[str]:
    out = []
    for it in items:
        item = getattr(it, "memory_item", it)
        out.append(getattr(item, "content", None) or str(item))
    return out


def memory_probe(project, store_name: str, chat_model: str, embedding_model: str) -> dict:
    """ストアがなければ作り、integrated_control に1件足して、scope の分離と削除を確かめる。"""
    from azure.ai.projects.models import MemorySearchOptions, MemoryStoreDefaultDefinition, MemoryStoreDefaultOptions

    steps: dict = {}
    ms = project.beta.memory_stores
    try:
        ms.get(store_name)
        steps["store"] = "exists"
    except Exception:  # noqa: BLE001 — ないときの例外の型は版で変わる
        ms.create(name=store_name, description="spike（確認 5）",
                  definition=MemoryStoreDefaultDefinition(
                      chat_model=chat_model, embedding_model=embedding_model,
                      options=MemoryStoreDefaultOptions(chat_summary_enabled=False, user_profile_enabled=True)))
        steps["store"] = "created"

    marker = f"連絡は朝まとめて（{uuid.uuid4().hex[:6]}）"
    created = ms.create_memory(name=store_name, scope="integrated_control", content=marker, kind="user_profile")
    memory_id = created.memory_id
    steps["created"] = {"memory_id": memory_id, "content": created.content}
    time.sleep(3)

    query = [{"role": "user", "content": "連絡のタイミングの好みは？", "type": "message"}]
    other = ms.search_memories(name=store_name, scope="motor_control", items=query,
                               options=MemorySearchOptions(max_memories=5))
    steps["search_other_scope"] = _texts(other.memories)
    own = ms.search_memories(name=store_name, scope="integrated_control", items=query,
                             options=MemorySearchOptions(max_memories=5))
    steps["search_own_scope"] = _texts(own.memories)
    steps["list_own_scope"] = _texts(ms.list_memories(name=store_name, scope="integrated_control"))

    # ほかの scope の名前で消せるか（項目 ID だけで消せてしまうなら、MCP 側で scope を確かめる必要がある）
    ms.delete_memory(name=store_name, memory_id=memory_id)
    steps["deleted"] = memory_id
    time.sleep(3)
    steps["list_after_delete"] = _texts(ms.list_memories(name=store_name, scope="integrated_control"))

    steps["ok"] = (
        marker not in " ".join(steps["search_other_scope"])
        and marker in " ".join(steps["list_own_scope"])
        and marker not in " ".join(steps["list_after_delete"])
    )
    return steps
