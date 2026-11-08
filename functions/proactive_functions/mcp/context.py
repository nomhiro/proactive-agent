"""道具に渡す呼び出しの文脈と、道具の拒否。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from vehicle_core.constants import Team


class ToolError(Exception):
    """道具の中の拒否や入力の誤り。tools/call の結果に isError: true と理由（日本語）を入れて返す。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ToolContext(BaseModel):
    """呼び出し元のチーム（トークンから決めたもの）と、道具が使う依存。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    team: Team
    store: Any  # proactive_functions.store.Store
    now: datetime  # 仮想時計の現在時刻
    memory: Any = None  # mcp.memory.MemoryBackend
    blobs: Any = None  # blobs.BlobReader
