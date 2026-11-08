"""チーフエンジニアに判断を仰ぐ（escalation）かどうかの判定。

前に出るのは、人が「できない」と返したとき、または期限までに返事がないときだけ（計画の決定3）。
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from .clock import to_jst
from .constants import REPLY_DEADLINE
from .models import AgentMail, MailKind, Stance


class EscalationDecision(BaseModel):
    escalate: bool
    reason: Literal["cannot", "no_reply"] | None


def needs_escalation(thread: Iterable[AgentMail], now: datetime) -> EscalationDecision:
    now = to_jst(now)
    mails = list(thread)
    if any(m.kind == MailKind.ESCALATION for m in mails):
        return EscalationDecision(escalate=False, reason=None)
    replies = [m for m in mails if m.kind == MailKind.HUMAN_REPLY]
    if any(m.stance == Stance.CANNOT for m in replies):
        return EscalationDecision(escalate=True, reason="cannot")
    replied_teams = {m.from_team for m in replies}
    for notice in (m for m in mails if m.kind == MailKind.IMPACT_NOTICE):
        if notice.to_team not in replied_teams and now - notice.created_at >= REPLY_DEADLINE:
            return EscalationDecision(escalate=True, reason="no_reply")
    return EscalationDecision(escalate=False, reason=None)
