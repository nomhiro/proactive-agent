"""エージェントの書き込みを受け付ける窓口の検査（設計書 7.5 節）。

エージェントは Cosmos DB を読むことしかできない。書き込みはすべてこの検査を通る。
Cosmos のロールではコンテナーより細かく絞れないため、メールの種類や宛先はここで確かめる。
"""

from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from .constants import AGENT_TEAMS, VEHICLE_ID, Team
from .models import CONTAINER_MODELS, AgentMail, MailKind, Message, MessageRole


class WriteDenied(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


AGENT_WRITABLE: frozenset[str] = frozenset(
    {"messages", "proposals", "notifications", "agent_runs", "watches", "schedules", "agent_mail"}
)

# エージェントが承認なしで送れるメール。impact_notice は人の承認を経て BFF が書く
AGENT_MAIL_ALLOWED: frozenset[MailKind] = frozenset({
    MailKind.ANALYSIS_REQUEST, MailKind.ANALYSIS_RESULT, MailKind.QUESTION,
    MailKind.ANSWER, MailKind.HUMAN_REPLY, MailKind.ESCALATION,
})


def authorize_agent_write(
    caller_team: str | None,
    container: str,
    doc: dict,
    lookup_message: Callable[[str], Message | None],
) -> BaseModel:
    """許可なら検証済みのモデルを返す。拒否なら WriteDenied。"""
    team = _caller(caller_team)

    if container not in AGENT_WRITABLE:
        raise WriteDenied(f"エージェントは {container} に書き込めません")

    try:
        model = CONTAINER_MODELS[container].model_validate(doc)
    except ValidationError as e:
        raise WriteDenied(f"文書の形式が正しくありません（{e.error_count()} 件の誤り）") from None

    if model.vehicle_id != VEHICLE_ID:
        raise WriteDenied("車種 ID が違います")

    if isinstance(model, AgentMail):
        _check_mail(team, model, lookup_message)
    else:
        if model.team != team:
            raise WriteDenied("ほかのチームの文書は書けません")
        if isinstance(model, Message) and model.role != MessageRole.ASSISTANT:
            raise WriteDenied("エージェントが書けるのはアシスタントの発言だけです")
    return model


def _caller(caller_team: str | None) -> Team:
    if not caller_team:
        raise WriteDenied("呼び出し元のチームがわかりません")
    try:
        team = Team(caller_team)
    except ValueError:
        raise WriteDenied(f"知らないチームです: {caller_team}") from None
    if team not in AGENT_TEAMS:
        raise WriteDenied(f"{caller_team} にはアシスタントがいません")
    return team


def _check_mail(team: Team, mail: AgentMail, lookup_message: Callable[[str], Message | None]) -> None:
    if mail.from_team != team:
        raise WriteDenied("送り主のチームが呼び出し元と違います")
    if mail.kind not in AGENT_MAIL_ALLOWED:
        raise WriteDenied(f"{mail.kind} は人の承認が必要です")
    if mail.to_team not in AGENT_TEAMS or mail.to_team == team:
        raise WriteDenied("宛先のチームが正しくありません")
    if mail.kind == MailKind.ESCALATION and mail.to_team != Team.CHIEF_ENGINEER:
        raise WriteDenied("判断の依頼はチーフエンジニアにだけ送れます")
    if mail.kind == MailKind.HUMAN_REPLY:
        source = lookup_message(mail.source_message_id) if mail.source_message_id else None
        if source is None or source.role != MessageRole.HUMAN or source.team != team:
            raise WriteDenied("人の返事には、自チームの人が書いた発言の ID が必要です")
