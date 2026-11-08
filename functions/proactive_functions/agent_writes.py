"""エージェントの書き込みの保存（設計書 7.5 節）。MCP の書き込みの道具から呼ぶ。

呼び出し元のチームは、トークンの client ID と team_settings.agent_client_id の対応表で決める。
"""

from .store import Store


def team_for_client(store: Store, client_id: str) -> str | None:
    found = store.query("team_settings", {"agent_client_id": client_id})
    return found[0]["team"] if found else None
