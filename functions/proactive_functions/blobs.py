"""Blob の読み書き（HILS ログ）。path は「コンテナ/名前」。キーは使わず、マネージド ID で読む。"""

from typing import Protocol


class BlobReader(Protocol):
    def read_text(self, path: str) -> str | None: ...


class BlobWriter(Protocol):
    def write_text(self, path: str, text: str) -> None: ...


def _split(path: str) -> tuple[str, str]:
    container, _, name = path.partition("/")
    if not container or not name:
        raise ValueError(f"Blob の場所は「コンテナ/名前」で指定してください: {path}")
    return container, name


class AzureBlobs:
    def __init__(self, endpoint: str, credential) -> None:
        from azure.storage.blob import BlobServiceClient
        self._service = BlobServiceClient(endpoint, credential=credential)

    def read_text(self, path: str) -> str | None:
        from azure.core.exceptions import ResourceNotFoundError
        container, name = _split(path)
        try:
            return self._service.get_blob_client(container, name).download_blob().readall().decode("utf-8")
        except ResourceNotFoundError:
            return None

    def write_text(self, path: str, text: str) -> None:
        from azure.storage.blob import ContentSettings
        container, name = _split(path)
        self._service.get_blob_client(container, name).upload_blob(
            text.encode("utf-8"), overwrite=True, content_settings=ContentSettings(content_type="text/csv"))
