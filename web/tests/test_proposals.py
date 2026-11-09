import pytest
from vehicle_core.constants import VEHICLE_ID

from proactive_web.personas import PERSONAS
from proactive_web.proposals import DecisionError, decide_proposal
from tests.helpers import MORNING, NIGHT

NOW = MORNING


@pytest.fixture
def pstore(store):
    store.create("proposals", {
        "id": "prop-1", "vehicle_id": VEHICLE_ID, "team": "integrated_control", "kind": "impact_notice",
        "to_teams": ["motor_control", "evaluation"], "draft": "下書き", "related_artifact_ids": ["SIG-BrkPedalPos"],
        "thread_id": "th-1", "status": "pending", "decided_by": None, "decided_at": None,
        "created_at": NIGHT.isoformat()})
    return store


def test_approve_writes_one_mail_per_team_then_marks_approved(pstore):
    out = decide_proposal(pstore, "prop-1", PERSONAS["tanaka"], "approve", None, NOW)
    assert out["status"] == "approved" and out["decided_by"] == "tanaka" and out["decided_at"] == NOW.isoformat()
    assert sorted(m["id"] for m in pstore.query("agent_mail")) == ["am-prop-1-evaluation", "am-prop-1-motor_control"]
    m = pstore.get("agent_mail", "am-prop-1-motor_control")
    assert m["kind"] == "impact_notice" and m["from_team"] == "integrated_control" and m["to_team"] == "motor_control"
    assert m["thread_id"] == "th-1" and m["body"] == "下書き" and m["related_artifact_ids"] == ["SIG-BrkPedalPos"]
    assert m["created_at"] == NOW.isoformat()
    assert pstore.get("proposals", "prop-1")["status"] == "approved"


def test_approve_with_edited_draft_sends_edited_text(pstore):
    out = decide_proposal(pstore, "prop-1", PERSONAS["tanaka"], "approve", "直した本文", NOW)
    assert out["draft"] == "直した本文"
    assert pstore.get("agent_mail", "am-prop-1-motor_control")["body"] == "直した本文"


def test_other_team_persona_cannot_decide(pstore):  # Review Focus 1
    with pytest.raises(DecisionError) as e:
        decide_proposal(pstore, "prop-1", PERSONAS["sato"], "approve", None, NOW)
    assert e.value.status == 403 and pstore.query("agent_mail") == []
    assert pstore.get("proposals", "prop-1")["status"] == "pending"


def test_second_decision_is_conflict_and_writes_no_more_mail(pstore):  # Review Focus 2
    decide_proposal(pstore, "prop-1", PERSONAS["tanaka"], "approve", None, NOW)
    with pytest.raises(DecisionError) as e:
        decide_proposal(pstore, "prop-1", PERSONAS["tanaka"], "approve", None, NOW)
    assert e.value.status == 409 and len(pstore.query("agent_mail")) == 2


def test_concurrent_decision_detected_by_etag(pstore):  # Review Focus 2（二つの画面から同時）
    def other_screen_decides(container, doc):
        if container == "proposals":
            pstore.before_replace = None
            cur = pstore.get("proposals", "prop-1")
            pstore.upsert("proposals", cur | {"status": "rejected", "decided_by": "yamada"})
    pstore.before_replace = other_screen_decides
    with pytest.raises(DecisionError) as e:
        decide_proposal(pstore, "prop-1", PERSONAS["tanaka"], "approve", None, NOW)
    assert e.value.status == 409
    assert pstore.get("proposals", "prop-1")["status"] == "rejected"


def test_retry_after_mail_written_but_status_not_saved_completes_without_duplicates(pstore):
    pstore.create("agent_mail", {"id": "am-prop-1-motor_control", "vehicle_id": VEHICLE_ID, "thread_id": "th-1",
                                 "from_team": "integrated_control", "to_team": "motor_control",
                                 "kind": "impact_notice", "body": "下書き", "created_at": NOW.isoformat()})
    decide_proposal(pstore, "prop-1", PERSONAS["tanaka"], "approve", None, NOW)
    assert len(pstore.query("agent_mail")) == 2


def test_reject_writes_no_mail(pstore):
    assert decide_proposal(pstore, "prop-1", PERSONAS["tanaka"], "reject", None, NOW)["status"] == "rejected"
    assert pstore.query("agent_mail") == []


def test_empty_edited_draft_is_rejected(pstore):
    with pytest.raises(DecisionError) as e:
        decide_proposal(pstore, "prop-1", PERSONAS["tanaka"], "approve", "  ", NOW)
    assert e.value.status == 422


def test_missing_proposal_is_404(pstore):
    with pytest.raises(DecisionError) as e:
        decide_proposal(pstore, "prop-x", PERSONAS["tanaka"], "approve", None, NOW)
    assert e.value.status == 404
