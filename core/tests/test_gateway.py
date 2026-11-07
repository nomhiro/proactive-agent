import pytest

from vehicle_core.gateway import WriteDenied, authorize_agent_write
from vehicle_core.models import MailKind, Message

T = "2026-11-18T09:00:00+09:00"
HUMAN_MSG = Message(id="m-sato-1", team="motor_control", role="human", author="sato",
                    text="今週は v2.1 で手一杯で、R3 までに 20ms 対応は無理", created_at=T)
ASSISTANT_MSG = Message(id="m-agent-1", team="motor_control", role="assistant", author="agent",
                        text="R3 までの対応は無理とのことです", created_at=T)
lookup = {"m-sato-1": HUMAN_MSG, "m-agent-1": ASSISTANT_MSG}.get


def mail(**kw):
    base = dict(id="am1", thread_id="th1", from_team="integrated_control", to_team="evaluation",
                kind="analysis_request", body="周期変更の応答を見て", created_at=T)
    return base | kw


def msg(**kw):
    return dict(id="m1", team="integrated_control", role="assistant", author="agent", text="x", created_at=T) | kw


@pytest.mark.parametrize("caller", [None, "", "unknown_team", "battery_control"])
def test_unknown_or_non_agent_caller_denied(caller):
    with pytest.raises(WriteDenied):
        authorize_agent_write(caller, "messages", msg(), lookup)


@pytest.mark.parametrize("container", ["artifacts", "change_events", "test_runs", "team_settings"])
def test_source_data_containers_denied(container):
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", container, {"id": "x"}, lookup)


def test_own_team_assistant_message_allowed():
    assert authorize_agent_write("integrated_control", "messages", msg(), lookup).id == "m1"


def test_other_team_message_denied():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "messages", msg(team="motor_control"), lookup)


def test_agent_cannot_write_human_message():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "messages", msg(role="human"), lookup)


def test_analysis_request_allowed():
    assert authorize_agent_write("integrated_control", "agent_mail", mail(), lookup).kind == MailKind.ANALYSIS_REQUEST


def test_impact_notice_denied_for_agents():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "agent_mail", mail(kind="impact_notice", to_team="motor_control"), lookup)


def test_spoofed_sender_denied():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "agent_mail", mail(from_team="motor_control"), lookup)


def test_escalation_only_to_chief():
    ok = mail(kind="escalation", to_team="chief_engineer")
    assert authorize_agent_write("integrated_control", "agent_mail", ok, lookup)
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "agent_mail", mail(kind="escalation", to_team="motor_control"), lookup)


def test_human_reply_requires_own_team_human_message():
    reply = mail(from_team="motor_control", to_team="integrated_control", kind="human_reply",
                 body="R3 までの対応は無理", stance="cannot", source_message_id="m-sato-1")
    assert authorize_agent_write("motor_control", "agent_mail", reply, lookup)
    with pytest.raises(WriteDenied):  # 他チームの人の発言を自チームの返事として使う
        authorize_agent_write("evaluation", "agent_mail", reply | {"from_team": "evaluation"}, lookup)
    with pytest.raises(WriteDenied):  # 元の発言がない
        authorize_agent_write("motor_control", "agent_mail", reply | {"source_message_id": None}, lookup)


def test_human_reply_citing_assistant_message_denied():
    reply = mail(from_team="motor_control", to_team="integrated_control", kind="human_reply",
                 body="R3 までの対応は無理", stance="cannot", source_message_id="m-agent-1")
    with pytest.raises(WriteDenied):
        authorize_agent_write("motor_control", "agent_mail", reply, lookup)


def test_mail_to_self_or_non_agent_team_denied():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "agent_mail", mail(to_team="integrated_control"), lookup)
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "agent_mail", mail(to_team="battery_control"), lookup)


def test_wrong_vehicle_denied():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "messages", msg(vehicle_id="other-car"), lookup)


def test_invalid_doc_denied():
    with pytest.raises(WriteDenied):
        authorize_agent_write("integrated_control", "messages", {"id": "m1"}, lookup)


def test_denial_has_reason():
    with pytest.raises(WriteDenied) as e:
        authorize_agent_write(None, "messages", msg(), lookup)
    assert e.value.reason
