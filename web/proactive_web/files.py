"""解析のグラフ（決定 15、設計書 7.6 節）。

エージェントは Foundry Files に上げた PNG を、メッセージの添付に `foundry-file:<ID>` として入れる。
BFF は、その人物のチームで見せてよいメッセージの添付にある ID だけを、プロジェクトの OpenAI クライアントで取る
（エージェントのエンドポイント用のクライアントでは取れない。Plan 3 の申し送り）。
"""

import functools
from typing import Protocol

PREFIX = "foundry-file:"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class FileSource(Protocol):
    def content(self, file_id: str) -> bytes: ...


def allowed_file_ids(visible_messages: list[dict]) -> set[str]:
    return {a[len(PREFIX):] for m in visible_messages for a in m.get("attachments", [])
            if isinstance(a, str) and a.startswith(PREFIX)}


def media_type(data: bytes) -> str:
    return "image/png" if data.startswith(PNG_MAGIC) else "application/octet-stream"


class FoundryFiles:
    def __init__(self, project_endpoint: str, credential) -> None:
        self._endpoint = project_endpoint
        self._credential = credential

    @functools.cached_property
    def _openai(self):
        from azure.ai.projects import AIProjectClient
        project = AIProjectClient(endpoint=self._endpoint, credential=self._credential, allow_preview=True)
        return project.get_openai_client()

    def content(self, file_id: str) -> bytes:
        return self._openai.files.content(file_id).read()
