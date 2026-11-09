"""BFF（FastAPI）。/api/* を受け、それ以外はビルド済みの画面を返す（決定 1）。

依存（Store、時計、記憶、チャット、画面への合図、グラフ）は Deps にまとめ、テストでは偽物を渡す。
"""

import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from proactive_functions.store import Store
from vehicle_core.constants import JST
from vehicle_core.models import Artifact

from .auth import current_user
from .map_layout import build_map
from .personas import PERSONAS, Persona, persona_or_400
from .views import build_state

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


class Clock(Protocol):
    def now(self) -> datetime: ...


class MemoryReader(Protocol):
    def list(self, team: str) -> list[dict]: ...


class FoundryMemoryReader:
    """Memory ストアの項目を読む（Plan 3 の FoundryMemoryBackend を使う。scope はチームの値）。"""

    def __init__(self, project_endpoint: str, credential, store_name: str) -> None:
        self._endpoint = project_endpoint
        self._credential = credential
        self._store_name = store_name

    @functools.cached_property
    def _backend(self):
        from azure.ai.projects import AIProjectClient
        from proactive_functions.mcp.memory import FoundryMemoryBackend
        project = AIProjectClient(endpoint=self._endpoint, credential=self._credential, allow_preview=True)
        return FoundryMemoryBackend(project, self._store_name)

    def list(self, team: str) -> list[dict]:
        return [{"id": m.id, "text": m.text} for m in self._backend.search(team, None)]


def _real_now() -> datetime:
    return datetime.now(JST)


@dataclass
class Deps:
    store: Store
    clock: Clock
    memory: MemoryReader | None = None
    chat: Any = None
    realtime: Any = None
    files: Any = None
    system_now: Callable[[], datetime] = field(default=_real_now)
    auth_mode: str = "easyauth"


def deps_from_settings() -> Deps:
    from .settings import load_settings
    s = load_settings()
    if s.store == "memory":
        from .dev import dev_deps
        return dev_deps(auth_mode=s.auth)
    from azure.identity import DefaultAzureCredential
    from proactive_functions.clock import StoredClock
    from proactive_functions.store import CosmosStore
    credential = DefaultAzureCredential()
    store = CosmosStore(s.cosmos_endpoint, s.cosmos_database, credential)
    memory = (FoundryMemoryReader(s.foundry_project_endpoint, credential, s.memory_store_name)
              if s.foundry_project_endpoint and s.memory_store_name else None)
    return Deps(store=store, clock=StoredClock(store), memory=memory, auth_mode=s.auth)


def create_app(deps: Deps | None = None, *, static_dir: Path | None = None) -> FastAPI:
    deps = deps or deps_from_settings()
    static_dir = static_dir or STATIC_DIR
    app = FastAPI(title="proactive-agent", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.deps = deps

    def user(request: Request) -> str:
        name = current_user(request.headers, deps.auth_mode)
        if name is None:
            raise HTTPException(status_code=401, detail="サインインしてください")
        return name

    def persona(persona: str | None = None) -> Persona:
        return persona_or_400(persona)

    def memories(team: str) -> list[dict]:
        if deps.memory is None:
            return []
        try:
            return deps.memory.list(team)
        except Exception:  # noqa: BLE001 — 記憶が読めなくても画面は出す
            log.exception("memory list failed: %s", team)
            return []

    @app.get("/api/me")
    def me(name: str = Depends(user)) -> dict:
        return {"user": name, "personas": [p.as_dict() for p in PERSONAS.values()]}

    @app.get("/api/state")
    def state(_: str = Depends(user), p: Persona = Depends(persona)) -> dict:
        return build_state(deps.store, p, deps.clock.now(), memories(p.team.value))

    @app.get("/api/map")
    def map_(_: str = Depends(user)) -> dict:
        artifacts = [Artifact.model_validate(a) for a in deps.store.query("artifacts")]
        return build_map(artifacts)

    # --- ここより上に /api のルートを足す。画面の配信は最後に置く --------------------------

    @app.get("/{path:path}", include_in_schema=False)
    def static(path: str):
        if path.startswith("api/") or path == "api":
            raise HTTPException(status_code=404, detail="ありません")
        root = static_dir.resolve()
        target = (root / path).resolve()
        if path and target.is_file() and root in target.parents:
            return FileResponse(target)
        index = root / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="画面がビルドされていません")
        return FileResponse(index)

    return app
