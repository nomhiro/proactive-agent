"""人の承認（決定 7、設計書 4.2 節）。impact_notice を agent_mail に書くのは、ここだけ。

承認では、まず提案を etag 付きで pending → approved に書き換えて確保し、そのあとで宛先ごとのメール
（ID am-<提案 ID>-<宛先チーム>）を書く。却下と同時に押されても、確保に負けた側はメールを書かない。
メールを書く途中で止まっても、同じチームがもう一度承認を押せば、保存した本文で足りない分を書く。
却下できるのは pending のときだけ。
"""

from datetime import datetime
from typing import Literal

from proactive_functions.store import Conflict, NotFound, Store
from vehicle_core.clock import to_jst
from vehicle_core.models import AgentMail, Proposal, ProposalStatus

from .personas import Persona


class DecisionError(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def mail_id(proposal_id: str, team: str) -> str:
    return f"am-{proposal_id}-{team}"


def _load(store: Store, proposal_id: str) -> tuple[dict, Proposal]:
    doc = store.get("proposals", proposal_id)
    if doc is None:
        raise DecisionError(404, "提案がありません")
    return doc, Proposal.model_validate(doc)


def _send_mails(store: Store, proposal: Proposal, now: datetime) -> None:
    for team in proposal.to_teams:
        mail = AgentMail(id=mail_id(proposal.id, team.value), thread_id=proposal.thread_id,
                         from_team=proposal.team, to_team=team, kind=proposal.kind, body=proposal.draft,
                         related_artifact_ids=proposal.related_artifact_ids, created_at=now)
        try:
            store.create("agent_mail", mail.model_dump(mode="json"))
        except Conflict:
            pass  # 前回の途中まで書いた分


def decide_proposal(store: Store, proposal_id: str, persona: Persona, action: Literal["approve", "reject"],
                    draft: str | None, now: datetime) -> dict:
    now = to_jst(now)
    doc, proposal = _load(store, proposal_id)
    if proposal.team != persona.team:
        raise DecisionError(403, "このチームの提案ではありません")
    if action == "approve" and proposal.status == ProposalStatus.APPROVED:
        _send_mails(store, proposal, now)  # 確保したあと、メールを書く途中で止まった分を揃える
        return doc
    if proposal.status != ProposalStatus.PENDING:
        raise DecisionError(409, "この提案はすでに決まっています")
    text = proposal.draft if draft is None else draft.strip()
    if action == "approve" and not text:
        raise DecisionError(422, "送る本文が空です")
    status = ProposalStatus.APPROVED if action == "approve" else ProposalStatus.REJECTED
    decided = proposal.model_copy(update={"status": status, "decided_by": persona.id, "decided_at": now,
                                          "draft": text if action == "approve" else proposal.draft})
    try:
        saved = store.replace("proposals", doc | decided.model_dump(mode="json"), etag=doc["_etag"])
    except (Conflict, NotFound):
        raise DecisionError(409, "ほかの画面で先に決まりました") from None
    if action == "approve":
        _send_mails(store, decided, now)
    return saved
