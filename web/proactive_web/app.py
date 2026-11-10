"""BFF（FastAPI）。/api/* を受け、それ以外はビルド済みの画面を返す（決定 1）。

依存（Store、時計、記憶、チャット、画面への合図、グラフ）は Deps にまとめ、テストでは偽物を渡す。
"""

import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from proactive_functions.store import Conflict, NotFound, Store
from pydantic import BaseModel
from vehicle_core.constants import JST, Team
from vehicle_core.models import Artifact, Proactivity

from .auth import current_user
from .chat import ChatBusy, ChatFailed
from .files import allowed_file_ids, media_type
from .map_layout import build_map
from .personas import PERSONAS, Persona, persona_or_400
from .proposals import DecisionError, decide_proposal
from .views import build_state, clean, visible_messages

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


class DecisionBody(BaseModel):
    persona: str
    action: Literal["approve", "reject"]
    draft: str | None = None


class ChatBody(BaseModel):
    persona: str
    text: str


class ClockBody(BaseModel):
    at: str


class SettingsBody(BaseModel):
    persona: str
    proactivity: Proactivity


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
    from .files import FoundryFiles
    from .realtime import NoRealtime, WebPubSubUrls
    realtime = (WebPubSubUrls(s.webpubsub_endpoint, s.webpubsub_hub, credential) if s.webpubsub_endpoint
                else NoRealtime())
    files = FoundryFiles(s.foundry_project_endpoint, credential) if s.foundry_project_endpoint else None
    from .chat import ChatService, FoundryChatClient
    clock = StoredClock(store)
    chat = (ChatService(store, FoundryChatClient(s.foundry_project_endpoint, credential), clock.now)
            if s.foundry_project_endpoint else None)
    return Deps(store=store, clock=clock, memory=memory, chat=chat, realtime=realtime, files=files,
                auth_mode=s.auth)


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
        if deps.chat is not None and deps.chat.busy(p.team):
            try:
                deps.chat.sync(p.team)  # チャットの返事を受け取る（決定 4）
            except Exception:  # noqa: BLE001 — 受け取れなくても画面は出す
                log.exception("chat sync failed: %s", p.team)
        return build_state(deps.store, p, deps.clock.now(), memories(p.team.value))

    @app.post("/api/chat")
    def chat(body: ChatBody, _: str = Depends(user)) -> dict:
        p = persona_or_400(body.persona)
        if deps.chat is None:
            raise HTTPException(status_code=503, detail="チャットは設定されていません")
        try:
            return {"message_id": deps.chat.send(p, body.text)}
        except ChatBusy as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
        except ChatFailed as e:
            raise HTTPException(status_code=502, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None

    @app.get("/api/map")
    def map_(_: str = Depends(user)) -> dict:
        artifacts = [Artifact.model_validate(a) for a in deps.store.query("artifacts")]
        return build_map(artifacts)

    @app.post("/api/proposals/{proposal_id}/decision")
    def decision(proposal_id: str, body: DecisionBody, _: str = Depends(user)) -> dict:
        p = persona_or_400(body.persona)
        try:
            return clean(decide_proposal(deps.store, proposal_id, p, body.action, body.draft, deps.clock.now()))
        except DecisionError as e:
            raise HTTPException(status_code=e.status, detail=e.reason) from None

    @app.put("/api/settings")
    def settings(body: SettingsBody, _: str = Depends(user)) -> dict:
        p = persona_or_400(body.persona)
        doc_id = f"ts-{p.team.value}"
        for _attempt in range(3):
            doc = deps.store.get("team_settings", doc_id)
            if doc is None:
                raise HTTPException(status_code=404, detail="チームの設定がありません")
            try:
                saved = deps.store.replace("team_settings", doc | {"proactivity": body.proactivity.value},
                                           etag=doc["_etag"])
                return {"proactivity": saved["proactivity"]}
            except (Conflict, NotFound):
                continue
        raise HTTPException(status_code=409, detail="ほかの操作と重なりました。もう一度試してください")

    @app.get("/api/negotiate")
    def negotiate(_: str = Depends(user), p: Persona = Depends(persona)) -> dict:
        groups = [t.value for t in Team] if p.team == Team.CHIEF_ENGINEER else [p.team.value]
        return {"url": deps.realtime.client_url(groups) if deps.realtime else None}

    @app.get("/api/files/{file_id}")
    def file(file_id: str, _: str = Depends(user), p: Persona = Depends(persona)) -> Response:
        notifications = {n["id"]: n for n in deps.store.query("notifications")}
        shown = visible_messages(deps.store.query("messages", {"team": p.team.value}), notifications)
        if deps.files is None or file_id not in allowed_file_ids(shown):
            raise HTTPException(status_code=404, detail="ファイルがありません")
        data = deps.files.content(file_id)
        return Response(content=data, media_type=media_type(data), headers={"Cache-Control": "private, max-age=3600"})

    def runner():
        from .scenario_runner import ScenarioRunner
        return ScenarioRunner(deps.store, deps.chat, system_now=deps.system_now)

    @app.get("/api/admin/steps")
    def admin_steps(_: str = Depends(user)) -> dict:
        return {"steps": runner().steps(), "now": deps.clock.now().isoformat()}

    @app.post("/api/admin/next")
    def admin_next(_: str = Depends(user)) -> dict:
        from .scenario_runner import StepNotReady
        if deps.chat is not None:
            try:
                deps.chat.sync(None)  # どの画面も開いていないチームの返事も受け取ってから進める
            except Exception:  # noqa: BLE001 — 受け取れなくても前提の確認で止まる
                log.exception("chat sync failed before next step")
        try:
            return runner().next()
        except StepNotReady as e:
            raise HTTPException(status_code=409, detail=e.reason) from None
        except DecisionError as e:
            raise HTTPException(status_code=e.status, detail=e.reason) from None

    @app.post("/api/admin/reset")
    def admin_reset(_: str = Depends(user)) -> dict:
        runner().reset()
        return {"ok": True}

    @app.post("/api/admin/clock")
    def admin_clock(body: ClockBody, _: str = Depends(user)) -> dict:
        from proactive_functions.clock import set_virtual_now
        try:
            at = datetime.fromisoformat(body.at)
            if at.tzinfo is None:
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=422, detail="タイムゾーン付きの ISO 8601 で指定してください") from None
        set_virtual_now(deps.store, at, deps.system_now())
        return {"now": deps.clock.now().isoformat()}

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
