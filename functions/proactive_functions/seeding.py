"""デモのデータ（シード）を Cosmos に入れる。

- reset=False: 足りない文書だけを新規作成する。時計の文書がなければ SEED_NOW に合わせる
- reset=True: leases 以外をすべて消して作り直し、時計を SEED_NOW に合わせる。
  team_settings の agent_client_id（Plan 3 が入れる）は引き継ぐ
- 書く文書にはすべて "origin": "seed" を付ける。変更フィードの処理はこれを飛ばす
"""

from datetime import datetime

from vehicle_core.seed import SEED_NOW, build_dataset, build_schedules

from .blobs import BlobWriter
from .clock import CLOCK_CONTAINER, CLOCK_ID, set_virtual_now
from .store import Conflict, Store

DATA_CONTAINERS: tuple[str, ...] = (
    "artifacts", "change_events", "test_runs", "watches", "messages", "proposals", "agent_mail",
    "notifications", "agent_runs", "schedules", "team_settings", "investigations", "system",
)


def _seed_docs() -> dict[str, list[dict]]:
    ds = build_dataset()
    tag = {"origin": "seed"}
    return {
        "artifacts": [a.model_dump(mode="json") | tag for a in ds.artifacts],
        "test_runs": [r.model_dump(mode="json") | tag for r in ds.test_runs],
        "team_settings": [t.model_dump(mode="json") | tag for t in ds.team_settings],
        "schedules": [s.model_dump(mode="json") | tag for s in build_schedules(ds)],
    }


def seed_store(store: Store, *, reset: bool, system_now: datetime) -> dict[str, int]:
    kept_client_ids: dict[str, str] = {}
    if reset:
        kept_client_ids = {t["id"]: t["agent_client_id"] for t in store.query("team_settings")
                           if t.get("agent_client_id")}
        for container in DATA_CONTAINERS:
            for doc in store.query(container):
                store.delete(container, doc["id"])

    counts: dict[str, int] = {}
    for container, docs in _seed_docs().items():
        counts[container] = 0
        for doc in docs:
            if container == "team_settings" and doc["id"] in kept_client_ids:
                doc = doc | {"agent_client_id": kept_client_ids[doc["id"]]}
            try:
                store.create(container, doc)
            except Conflict:
                continue
            counts[container] += 1

    if reset or store.get(CLOCK_CONTAINER, CLOCK_ID) is None:
        set_virtual_now(store, SEED_NOW, system_now)
        from .foundry_invoker import record_clock_baseline
        record_clock_baseline(store, SEED_NOW, store.get(CLOCK_CONTAINER, CLOCK_ID)["offset_seconds"])
    return counts


def upload_hils_logs(writer: BlobWriter, logs: dict[str, str]) -> int:
    """HILS ログを Blob に置く（上書き）。logs は「コンテナ/名前」→ CSV。置いた件数を返す。"""
    for path, text in logs.items():
        writer.write_text(path, text)
    return len(logs)
