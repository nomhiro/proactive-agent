"""読み取りの道具（設計書 7.5 節）。範囲は scope.py の表に従う。"""

import logging
from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict
from vehicle_core.constants import TEAM_LABELS_JA, Team
from vehicle_core.impact import analyze_impact
from vehicle_core.models import Artifact, ArtifactType, TeamSettings, TestRun
from vehicle_core.release_gaps import release_gaps
from vehicle_core.seed import Dataset

from ..docs import parse_each
from ..handlers import load_graph
from .context import ToolContext, ToolError
from .protocol import Registry, Tool
from .scope import effective_team, read_scope

log = logging.getLogger(__name__)

LOG_LIMIT = 200_000
SEARCH_LIMIT_MAX = 200
LIST_LIMIT = 50


class _Args(BaseModel):
    model_config = ConfigDict(extra="ignore")


def clean(doc: dict) -> dict:
    """保存先の内部の項目（_etag など）とシードの印を除く。"""
    return {k: v for k, v in doc.items() if not k.startswith("_") and k != "origin"}


def _newest(docs: list[dict], key: str, limit: int | None = None) -> list[dict]:
    out = sorted((clean(d) for d in docs), key=lambda d: str(d.get(key) or ""), reverse=True)
    return out[:limit] if limit else out


def _team_filter(ctx: ToolContext, container: str, requested: str | None) -> dict:
    assert read_scope(container) == "own_or_chief"
    team = effective_team(ctx.team, requested)
    return {} if team is None else {"team": team.value}


# --- 開発データ -------------------------------------------------------------

class ArtifactArgs(_Args):
    artifact_id: str


def get_artifact(ctx: ToolContext, args: dict) -> dict:
    a = ArtifactArgs.model_validate(args)
    doc = ctx.store.get("artifacts", a.artifact_id)
    if doc is None:
        raise ToolError(f"データがありません: {a.artifact_id}")
    return clean(doc)


class SearchArgs(_Args):
    type: ArtifactType | None = None
    team: Team | None = None
    text: str | None = None
    limit: int = 50


def search_artifacts(ctx: ToolContext, args: dict) -> list[dict]:
    a = SearchArgs.model_validate(args)
    where = {k: v.value for k, v in (("type", a.type), ("team", a.team)) if v is not None}
    out = []
    for doc, art in parse_each(ctx.store.query("artifacts", where or None), Artifact):
        if a.text and a.text not in f"{art.id} {art.title} {art.description}":
            continue
        out.append({"id": art.id, "type": art.type.value, "team": art.team.value, "title": art.title,
                    "owner": art.owner, "version": art.version, "status": art.status, "links": art.links})
    out.sort(key=lambda d: d["id"])
    return out[:max(1, min(a.limit, SEARCH_LIMIT_MAX))]


def trace_impact(ctx: ToolContext, args: dict) -> dict:
    a = ArtifactArgs.model_validate(args)
    graph = load_graph(ctx.store)
    if not graph.has(a.artifact_id):
        raise ToolError(f"データがありません: {a.artifact_id}")
    return analyze_impact(graph, a.artifact_id).model_dump(mode="json")


class TestRunsArgs(_Args):
    testcase_id: str


def get_test_runs(ctx: ToolContext, args: dict) -> list[dict]:
    a = TestRunsArgs.model_validate(args)
    return _newest(ctx.store.query("test_runs", {"testcase_id": a.testcase_id}), "executed_at")


class TestLogArgs(_Args):
    test_run_id: str


def get_test_log(ctx: ToolContext, args: dict) -> dict:
    a = TestLogArgs.model_validate(args)
    doc = ctx.store.get("test_runs", a.test_run_id)
    if doc is None:
        raise ToolError(f"試験結果がありません: {a.test_run_id}")
    run = TestRun.model_validate(doc)
    text = None
    if run.log_blob and ctx.blobs is not None:
        try:
            text = ctx.blobs.read_text(run.log_blob)
        except ValueError:  # 「コンテナ/名前」の形でない log_blob は、ログがないのと同じ
            text = None
        except Exception:  # noqa: BLE001 — Storage の権限や通信の失敗
            log.exception("get_test_log: blob read failed: %s", run.log_blob)
            raise ToolError(f"ログを読めませんでした: {a.test_run_id}") from None
    if text is None:
        raise ToolError(f"ログがありません: {a.test_run_id}")
    return {"test_run_id": run.id, "csv": text[:LOG_LIMIT], "truncated": len(text) > LOG_LIMIT}


class ReleaseArgs(_Args):
    release_id: str


def get_release_gaps(ctx: ToolContext, args: dict) -> dict:
    a = ReleaseArgs.model_validate(args)
    rel = ctx.store.get("artifacts", a.release_id)
    if rel is None or rel.get("type") != ArtifactType.RELEASE.value:
        raise ToolError(f"統合リリースがありません: {a.release_id}")
    ds = Dataset(artifacts=[m for _, m in parse_each(ctx.store.query("artifacts"), Artifact)],
                 test_runs=[m for _, m in parse_each(ctx.store.query("test_runs"), TestRun)],
                 team_settings=[], people=[])
    return release_gaps(ds, a.release_id).model_dump(mode="json")


# --- チーム -----------------------------------------------------------------

def list_team_members(ctx: ToolContext, args: dict) -> list[dict]:
    out = []
    for _, ts in parse_each(ctx.store.query("team_settings"), TeamSettings):
        out.append({"team": ts.team.value, "label_ja": TEAM_LABELS_JA[ts.team],
                    "members": [{"id": p.id, "name_ja": p.name_ja, "role": p.role} for p in ts.members]})
    return sorted(out, key=lambda t: t["team"])


def get_team_settings(ctx: ToolContext, args: dict) -> dict:
    found = [m for _, m in parse_each(ctx.store.query("team_settings", {"team": ctx.team.value}), TeamSettings)]
    ts = found[0] if found else TeamSettings(id=f"ts-{ctx.team.value}", team=ctx.team)
    return ts.model_dump(mode="json", include={"team", "proactivity", "quiet_start", "quiet_end", "members"})


# --- 一覧（自チーム分。統括は全チーム分） ------------------------------------

class TeamListArgs(_Args):
    team: str | None = None


class NotificationsArgs(TeamListArgs):
    since: AwareDatetime | None = None


def list_notifications(ctx: ToolContext, args: dict) -> list[dict]:
    a = NotificationsArgs.model_validate(args)
    docs = ctx.store.query("notifications", _team_filter(ctx, "notifications", a.team) or None)
    if a.since:  # 文字列ではなく時刻で比べる（タイムゾーンの違う since でも範囲がずれない）
        docs = [d for d in docs if d.get("created_at") and datetime.fromisoformat(d["created_at"]) >= a.since]
    return _newest(docs, "created_at", LIST_LIMIT)


class ProposalsArgs(TeamListArgs):
    status: str | None = None


def list_proposals(ctx: ToolContext, args: dict) -> list[dict]:
    a = ProposalsArgs.model_validate(args)
    where = _team_filter(ctx, "proposals", a.team) | ({"status": a.status} if a.status else {})
    return _newest(ctx.store.query("proposals", where or None), "created_at", LIST_LIMIT)


class RunsArgs(TeamListArgs):
    state: str | None = None


def list_runs(ctx: ToolContext, args: dict) -> list[dict]:
    a = RunsArgs.model_validate(args)
    where = _team_filter(ctx, "agent_runs", a.team) | ({"state": a.state} if a.state else {})
    return _newest(ctx.store.query("agent_runs", where or None), "started_at", LIST_LIMIT)


def list_schedules(ctx: ToolContext, args: dict) -> list[dict]:
    a = TeamListArgs.model_validate(args)
    docs = ctx.store.query("schedules", _team_filter(ctx, "schedules", a.team) or None)
    return sorted((clean(d) for d in docs), key=lambda d: str(d.get("due_at", "")))


class MailArgs(TeamListArgs):
    thread_id: str | None = None


def list_mail(ctx: ToolContext, args: dict) -> list[dict]:
    a = MailArgs.model_validate(args)
    team = effective_team(ctx.team, a.team)
    docs = ctx.store.query("agent_mail", {"thread_id": a.thread_id} if a.thread_id else None)
    if team is not None:
        docs = [d for d in docs if team.value in (d.get("from_team"), d.get("to_team"))]
    return sorted((clean(d) for d in docs), key=lambda d: str(d.get("created_at", "")))[-LIST_LIMIT:]


class MessagesArgs(_Args):
    limit: int = 20


def list_messages(ctx: ToolContext, args: dict) -> list[dict]:
    a = MessagesArgs.model_validate(args)
    return _newest(ctx.store.query("messages", {"team": ctx.team.value}), "created_at", max(1, min(a.limit, 100)))


def list_watches(ctx: ToolContext, args: dict) -> list[dict]:
    return _newest(ctx.store.query("watches", {"team": ctx.team.value}), "created_at")


# --- 登録 -------------------------------------------------------------------

def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


_S: dict[str, Any] = {"type": "string"}
_TEAM = {"type": "string", "enum": [t.value for t in Team],
         "description": "統括だけが使える。ほかのチームが渡しても自チームとして扱う"}

TOOLS = [
    Tool("get_artifact", "開発データ（要求、仕様、信号、モデル、テスト、安全要求、リリース、レビュー）を ID で1件読む。",
         _schema({"artifact_id": _S}, ["artifact_id"]), get_artifact),
    Tool("search_artifacts", "開発データを種類、チーム、文字列（ID、題名、説明の部分一致）で探す。結果は要約（上限 200 件）。",
         _schema({"type": {"type": "string", "enum": [t.value for t in ArtifactType]},
                  "team": {"type": "string", "enum": [t.value for t in Team]}, "text": _S,
                  "limit": {"type": "integer", "minimum": 1}}), search_artifacts),
    Tool("trace_impact", "あるデータを起点に、トレーサビリティを辿って影響を受けるデータ、チーム、リリース、安全要求への影響を計算する。"
         "影響範囲は必ずこれで求め、自分で推測しない。", _schema({"artifact_id": _S}, ["artifact_id"]), trace_impact),
    Tool("get_test_runs", "テストケースの試験結果の履歴を新しい順に返す。", _schema({"testcase_id": _S}, ["testcase_id"]),
         get_test_runs),
    Tool("get_test_log", "試験結果の HILS ログ（CSV のテキスト）を返す。作業環境で解析するときは、ファイルに書いてから使う。",
         _schema({"test_run_id": _S}, ["test_run_id"]), get_test_log),
    Tool("get_release_gaps", "統合リリースについて、未検証の要求、未完了のレビュー、検証の済んでいない安全要求を集計する。",
         _schema({"release_id": _S}, ["release_id"]), get_release_gaps),
    Tool("list_team_members", "全チームのメンバーと役割を返す。", _schema({}), list_team_members),
    Tool("get_team_settings", "自チームの設定（話しかける頻度、静かな時間帯、メンバー）を返す。", _schema({}), get_team_settings),
    Tool("list_notifications", "通知の一覧（新しい順）。since で日時以降に絞れる。",
         _schema({"team": _TEAM, "since": _S}), list_notifications),
    Tool("list_proposals", "承認待ちなどの提案の一覧（新しい順）。status は pending / approved / rejected。",
         _schema({"team": _TEAM, "status": _S}), list_proposals),
    Tool("list_runs", "作業記録の一覧（新しい順）。state は running / scheduled / done。",
         _schema({"team": _TEAM, "state": _S}), list_runs),
    Tool("list_schedules", "予定の一覧（近い順）。", _schema({"team": _TEAM}), list_schedules),
    Tool("list_mail", "エージェント間メールの一覧（古い順）。自チームが送り手か宛先のもの。統括は全件。thread_id で絞れる。",
         _schema({"team": _TEAM, "thread_id": _S}), list_mail),
    Tool("list_messages", "自チームの会話欄のメッセージ（新しい順）。", _schema({"limit": {"type": "integer", "minimum": 1}}),
         list_messages),
    Tool("list_watches", "自チームの見張りの一覧。", _schema({}), list_watches),
]


def register_read_tools(registry: Registry) -> None:
    for t in TOOLS:
        registry.add(t)
