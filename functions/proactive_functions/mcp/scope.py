"""読み取りの範囲（設計書 7.5 節の表）。範囲はこの1か所で決める。

- all: 全チーム分（開発データ、変更、試験結果）
- own_or_chief: 自チーム分。統括は全チーム分（ブリーフィング、リリース前チェック、エスカレーションに要る）
- own: 自チーム分だけ（統括も自分の分だけ）
- members: 全チームのメンバーと役割だけ
"""

from typing import Literal

from vehicle_core.constants import Team

from .context import ToolError

Scope = Literal["all", "own_or_chief", "own", "members"]

READ_SCOPE: dict[str, Scope] = {
    "artifacts": "all",
    "change_events": "all",
    "test_runs": "all",
    "notifications": "own_or_chief",
    "proposals": "own_or_chief",
    "agent_runs": "own_or_chief",
    "schedules": "own_or_chief",
    "agent_mail": "own_or_chief",
    "messages": "own",
    "watches": "own",
    "investigations": "own",
    "team_settings": "members",
}


def read_scope(container: str) -> Scope:
    return READ_SCOPE[container]


def effective_team(caller: Team, requested: str | None) -> Team | None:
    """一覧の道具の team 引数を解決する。統括だけが別のチーム（None なら全チーム）を選べる。"""
    if caller != Team.CHIEF_ENGINEER:
        return caller
    if requested is None:
        return None
    try:
        return Team(requested)
    except ValueError:
        raise ToolError(f"知らないチームです: {requested}") from None
