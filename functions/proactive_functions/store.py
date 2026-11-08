"""文書の保存先。Functions の処理はこの Store プロトコルだけを使う（テストでは偽物を渡す）。

すべての文書は vehicle_id を持ち、パーティションキーは VEHICLE_ID（PoC は1車種）。
返す文書には Cosmos の `_etag` が入る。
"""

import re
from typing import Any, Protocol

from azure.core import MatchConditions
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from vehicle_core.constants import VEHICLE_ID


class Conflict(Exception):
    """同じ ID の文書が既にある、または etag が合わない。"""


class NotFound(Exception):
    """文書がない。"""


class Store(Protocol):
    def get(self, container: str, id: str) -> dict | None: ...
    def create(self, container: str, doc: dict) -> dict: ...
    def upsert(self, container: str, doc: dict) -> dict: ...
    def replace(self, container: str, doc: dict, *, etag: str) -> dict: ...
    def delete(self, container: str, id: str) -> None: ...
    def query(self, container: str, where: dict[str, Any] | None = None) -> list[dict]: ...


_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def build_query(where: dict[str, Any] | None) -> tuple[str, list[dict]]:
    """等号の AND。値が None の条件は「項目がない、または null」。"""
    clauses, params = [], []
    for i, (field, value) in enumerate((where or {}).items()):
        if not _FIELD.match(field):
            raise ValueError(f"使えない項目名です: {field}")
        if value is None:
            clauses.append(f"(NOT IS_DEFINED(c.{field}) OR IS_NULL(c.{field}))")
        else:
            clauses.append(f"c.{field} = @p{i}")
            params.append({"name": f"@p{i}", "value": value})
    sql = "SELECT * FROM c" + (" WHERE " + " AND ".join(clauses) if clauses else "")
    return sql, params


class CosmosStore:
    def __init__(self, endpoint: str, database: str, credential) -> None:
        self._db = CosmosClient(endpoint, credential=credential).get_database_client(database)

    def _c(self, container: str):
        return self._db.get_container_client(container)

    def get(self, container: str, id: str) -> dict | None:
        try:
            return self._c(container).read_item(item=id, partition_key=VEHICLE_ID)
        except CosmosResourceNotFoundError:
            return None

    def create(self, container: str, doc: dict) -> dict:
        try:
            return self._c(container).create_item(body=doc)
        except CosmosResourceExistsError:
            raise Conflict(doc["id"]) from None

    def upsert(self, container: str, doc: dict) -> dict:
        return self._c(container).upsert_item(body=doc)

    def replace(self, container: str, doc: dict, *, etag: str) -> dict:
        try:
            return self._c(container).replace_item(
                item=doc["id"], body=doc, etag=etag, match_condition=MatchConditions.IfNotModified)
        except CosmosAccessConditionFailedError:
            raise Conflict(doc["id"]) from None
        except CosmosResourceNotFoundError:
            raise NotFound(doc["id"]) from None

    def delete(self, container: str, id: str) -> None:
        try:
            self._c(container).delete_item(item=id, partition_key=VEHICLE_ID)
        except CosmosResourceNotFoundError:
            raise NotFound(id) from None

    def query(self, container: str, where: dict[str, Any] | None = None) -> list[dict]:
        sql, params = build_query(where)
        return list(self._c(container).query_items(query=sql, parameters=params, partition_key=VEHICLE_ID))
