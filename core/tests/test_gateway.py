from datetime import datetime

import pytest

from vehicle_core.constants import JST
from vehicle_core.gateway import ASSISTANT_AUTHOR, WriteDenied, authorize_agent_write
from vehicle_core.models import AgentMail, MailKind, Message

T = "2026-11-18T09:00:00+09:00"
HUMAN_MSG = Message(id="m-sato-1", team="motor_control", role="human", author="sato",
                    text="今週は v2.1 で手一杯で、R3 までに 20ms 対応は無理", created_at=T)
ASSISTANT_MSG = Message(id="m-agent-1", team="motor_control", role="assistant", author="agent",
                        text="R3 までの対応は無理とのことです", created_at=T)
GREETING = Message(id="m-sato-0", team="motor_control", role="human", author="sato",
                   text="おはようございます", created_at=T)
lookup = {"m-sato-1": HUMAN_MSG, "m-agent-1": ASSISTANT_MSG, "m-sato-0": GREETING}.get
NOW = datetime(2026, 11, 18, 9, 30, tzinfo=JST)
NOTICE = AgentMail(id="n1", thread_id="th1", from_team="integrated_control", to_team="motor_control",
                   kind="impact_notice", body="BrkPedalPos 周期変更", created_at=T)
CANNOT = AgentMail(id="r1", thread_id="th1", from_team="motor_control", to_team="integrated_control",
                   kind="human_reply", body=HUMAN_MSG.text, stance="cannot", source_message_id="m-sato-1",
                   created_at=T)
THREADS = {"th1": [NOTICE, CANNOT], "th-quiet": [NOTICE.model_copy(update={"thread_id": "th-quiet"})]}


def lookup_thread(thread_id):
    return THREADS.get(thread_id, [])


def aw(caller, container, doc, lookup_message):
    return authorize_agent_write(caller, container, doc, lookup_message, lookup_thread=lookup_thread, now=NOW)


def mail(**kw):
    base = dict(id="am1", thread_id="th1", from_team="integrated_control", to_team="evaluation",
                kind="analysis_request", body="周期変更の応答を見て", created_at=T)
    return base | kw


def msg(**kw):
    return dict(id="m1", team="integrated_control", role="assistant", author=ASSISTANT_AUTHOR, text="x", created_at=T) | kw


@pytest.mark.parametrize("caller", [None, "", "unknown_team", "battery_control"])
def test_unknown_or_non_agent_caller_denied(caller):
    with pytest.raises(WriteDenied):
        aw(caller, "messages", msg(), lookup)


@pytest.mark.parametrize("container", ["artifacts", "change_events", "test_runs", "team_settings"])
def test_source_data_containers_denied(container):
    with pytest.raises(WriteDenied):
        aw("integrated_control", container, {"id": "x"}, lookup)


def test_own_team_assistant_message_allowed():
    assert aw("integrated_control", "messages", msg(), lookup).id == "m1"


def test_other_team_message_denied():
    with pytest.raises(WriteDenied):
        aw("integrated_control", "messages", msg(team="motor_control"), lookup)


def test_agent_cannot_write_human_message():
    with pytest.raises(WriteDenied):
        aw("integrated_control", "messages", msg(role="human"), lookup)


def test_analysis_request_allowed():
    assert aw("integrated_control", "agent_mail", mail(), lookup).kind == MailKind.ANALYSIS_REQUEST


def test_impact_notice_denied_for_agents():
    with pytest.raises(WriteDenied):
        aw("integrated_control", "agent_mail", mail(kind="impact_notice", to_team="motor_control"), lookup)


def test_spoofed_sender_denied():
    with pytest.raises(WriteDenied):
        aw("integrated_control", "agent_mail", mail(from_team="motor_control"), lookup)


def test_escalation_only_to_chief():
    ok = mail(kind="escalation", to_team="chief_engineer")
    assert aw("integrated_control", "agent_mail", ok, lookup)
    with pytest.raises(WriteDenied):
        aw("integrated_control", "agent_mail", mail(kind="escalation", to_team="motor_control"), lookup)


def test_human_reply_requires_own_team_human_message():
    reply = mail(from_team="motor_control", to_team="integrated_control", kind="human_reply",
                 body=HUMAN_MSG.text, stance="cannot", source_message_id="m-sato-1")
    assert aw("motor_control", "agent_mail", reply, lookup)
    with pytest.raises(WriteDenied):  # 他チームの人の発言を自チームの返事として使う
        aw("evaluation", "agent_mail", reply | {"from_team": "evaluation"}, lookup)
    with pytest.raises(WriteDenied):  # 元の発言がない
        aw("motor_control", "agent_mail", reply | {"source_message_id": None}, lookup)


def test_human_reply_citing_assistant_message_denied():
    reply = mail(from_team="motor_control", to_team="integrated_control", kind="human_reply",
                 body="R3 までの対応は無理", stance="cannot", source_message_id="m-agent-1")
    with pytest.raises(WriteDenied):
        aw("motor_control", "agent_mail", reply, lookup)


def test_mail_to_self_or_non_agent_team_denied():
    with pytest.raises(WriteDenied):
        aw("integrated_control", "agent_mail", mail(to_team="integrated_control"), lookup)
    with pytest.raises(WriteDenied):
        aw("integrated_control", "agent_mail", mail(to_team="battery_control"), lookup)


def test_wrong_vehicle_denied():
    with pytest.raises(WriteDenied):
        aw("integrated_control", "messages", msg(vehicle_id="other-car"), lookup)


def test_invalid_doc_denied():
    with pytest.raises(WriteDenied):
        aw("integrated_control", "messages", {"id": "m1"}, lookup)


def test_denial_has_reason():
    with pytest.raises(WriteDenied) as e:
        aw(None, "messages", msg(), lookup)
    assert e.value.reason


def proposal(**kw):
    return dict(id="p1", team="integrated_control", kind="impact_notice", to_teams=["motor_control"],
                draft="BrkPedalPos の周期を 20ms に変えます", thread_id="th9", created_at=T) | kw


def test_pending_proposal_allowed():
    assert aw("integrated_control", "proposals", proposal(), lookup).status == "pending"


@pytest.mark.parametrize("extra", [
    {"status": "approved"},
    {"status": "rejected"},
    {"decided_by": "tanaka"},
    {"decided_at": T},
])
def test_agent_cannot_write_decided_proposal(extra):
    with pytest.raises(WriteDenied):
        aw("integrated_control", "proposals", proposal(**extra), lookup)


def test_human_reply_body_must_be_the_human_words():
    reply = mail(from_team="motor_control", to_team="integrated_control", kind="human_reply",
                 body="R3 までに対応は無理です", stance="cannot", source_message_id="m-sato-0")
    with pytest.raises(WriteDenied):
        aw("motor_control", "agent_mail", reply, lookup)


def test_escalation_without_grounds_denied():
    for thread in ["th-quiet", "th-none"]:
        with pytest.raises(WriteDenied):
            aw("integrated_control", "agent_mail",
               mail(kind="escalation", to_team="chief_engineer", thread_id=thread), lookup)


def test_escalation_after_deadline_allowed():
    later = datetime(2026, 11, 20, 9, 0, tzinfo=JST)
    doc = mail(kind="escalation", to_team="chief_engineer", thread_id="th-quiet")
    assert authorize_agent_write("integrated_control", "agent_mail", doc, lookup,
                                 lookup_thread=lookup_thread, now=later)


def test_assistant_message_cannot_claim_a_person_as_author():
    with pytest.raises(WriteDenied):
        aw("integrated_control", "messages", msg(author="tanaka"), lookup)


def test_created_at_is_set_by_the_gateway():
    m = aw("integrated_control", "messages", msg(created_at="2026-11-01T00:00:00+09:00"), lookup)
    assert m.created_at == NOW


def test_watch_with_zero_streak_denied():
    w = dict(id="w0", team="integrated_control", kind="test_failure_streak", description="x",
             feature="regen_coord", streak=0, delivery="immediate", created_by="tanaka", created_at=T)
    with pytest.raises(WriteDenied):
        aw("integrated_control", "watches", w, lookup)
