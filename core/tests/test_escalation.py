from datetime import datetime, timedelta, timezone

from vehicle_core.constants import JST
from vehicle_core.escalation import needs_escalation
from vehicle_core.models import AgentMail

T0 = datetime(2026, 11, 18, 9, 0, tzinfo=JST)
NOTICE = AgentMail(id="n1", thread_id="th1", from_team="integrated_control", to_team="motor_control",
                   kind="impact_notice", body="BrkPedalPos 周期変更", created_at=T0)


def reply(stance, minutes=30):
    return AgentMail(id=f"r-{stance}", thread_id="th1", from_team="motor_control", to_team="integrated_control",
                     kind="human_reply", body="...", stance=stance, source_message_id="m-sato-1",
                     created_at=T0 + timedelta(minutes=minutes))


def test_cannot_reply_escalates():
    d = needs_escalation([NOTICE, reply("cannot")], T0 + timedelta(hours=1))
    assert d.escalate and d.reason == "cannot"


def test_can_reply_does_not_escalate():
    assert needs_escalation([NOTICE, reply("can")], T0 + timedelta(hours=1)).escalate is False


def test_no_reply_after_48h_escalates():
    assert needs_escalation([NOTICE], T0 + timedelta(hours=47, minutes=59)).escalate is False
    d = needs_escalation([NOTICE], T0 + timedelta(hours=48))
    assert d.escalate and d.reason == "no_reply"


def test_already_escalated_thread_does_not_escalate_again():
    esc = AgentMail(id="e1", thread_id="th1", from_team="integrated_control", to_team="chief_engineer",
                    kind="escalation", body="...", created_at=T0 + timedelta(hours=2))
    assert needs_escalation([NOTICE, reply("cannot"), esc], T0 + timedelta(hours=3)).escalate is False


def test_deadline_uses_instants_not_wall_clock():
    utc_now = (T0 + timedelta(hours=48)).astimezone(timezone.utc)
    assert needs_escalation([NOTICE], utc_now).escalate is True
