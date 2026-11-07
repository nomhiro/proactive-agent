"""Cosmos DB に置くすべての文書の型。"""

from datetime import time
from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

from .constants import QUIET_END, QUIET_START, VEHICLE_ID, Team


class ArtifactType(StrEnum):
    REQUIREMENT = "requirement"
    SPEC = "spec"
    SIGNAL = "signal"
    MODEL = "model"
    TESTCASE = "testcase"
    SAFETY_REQUIREMENT = "safety_requirement"
    RELEASE = "release"
    REVIEW = "review"


class Artifact(BaseModel):
    """開発データ（要求、仕様、信号、モデル、テスト、安全要求、リリース、レビュー）。"""

    id: str
    vehicle_id: str = VEHICLE_ID
    type: ArtifactType
    team: Team
    title: str
    description: str = ""
    owner: str
    version: str = "1.0"
    status: str = "active"
    links: list[str] = []  # 上流（このデータが依って立つもの）の ID
    attributes: dict[str, Any] = {}
    release_ids: list[str] = []
    updated_at: AwareDatetime


class FieldChange(BaseModel):
    path: str
    before: Any
    after: Any


# 中身に影響しない、編集上の項目
EDITORIAL_FIELDS = {"title", "description"}


class ChangeEvent(BaseModel):
    id: str
    vehicle_id: str = VEHICLE_ID
    artifact_id: str
    changed_by: str
    changed_at: AwareDatetime
    changes: list[FieldChange]

    @property
    def is_substantive(self) -> bool:
        return any(c.path not in EDITORIAL_FIELDS for c in self.changes)


class TestRun(BaseModel):
    __test__ = False  # pytest に集めさせない

    id: str
    vehicle_id: str = VEHICLE_ID
    testcase_id: str
    feature: str
    result: Literal["pass", "fail"]
    executed_at: AwareDatetime
    log_blob: str | None = None


class WatchKind(StrEnum):
    ARTIFACT_CHANGED = "artifact_changed"
    TEST_FAILURE_STREAK = "test_failure_streak"


class DeliveryMode(StrEnum):
    IMMEDIATE = "immediate"
    DIGEST = "digest"


class Watch(BaseModel):
    id: str
    vehicle_id: str = VEHICLE_ID
    team: Team
    kind: WatchKind
    description: str
    target_ids: list[str] = []
    feature: str | None = None
    streak: int = Field(3, ge=1)
    delivery: DeliveryMode
    created_by: str
    created_at: AwareDatetime


class Classification(StrEnum):
    """知らせ方。silent < digest < notify_now の順に強い。"""

    SILENT = "silent"
    DIGEST = "digest"
    NOTIFY_NOW = "notify_now"


class Proactivity(StrEnum):
    OFF = "off"
    IMPORTANT_ONLY = "important_only"
    NORMAL = "normal"
    FREQUENT = "frequent"


class Person(BaseModel):
    id: str
    name_ja: str
    team: Team
    role: str


class TeamSettings(BaseModel):
    id: str
    vehicle_id: str = VEHICLE_ID
    team: Team
    proactivity: Proactivity = Proactivity.NORMAL
    quiet_start: time = QUIET_START
    quiet_end: time = QUIET_END
    members: list[Person] = []


class MailKind(StrEnum):
    ANALYSIS_REQUEST = "analysis_request"
    ANALYSIS_RESULT = "analysis_result"
    QUESTION = "question"
    ANSWER = "answer"
    IMPACT_NOTICE = "impact_notice"
    HUMAN_REPLY = "human_reply"
    ESCALATION = "escalation"


class Stance(StrEnum):
    CAN = "can"
    CANNOT = "cannot"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class AgentMail(BaseModel):
    id: str
    vehicle_id: str = VEHICLE_ID
    thread_id: str
    from_team: Team
    to_team: Team
    kind: MailKind
    body: str
    related_artifact_ids: list[str] = []
    source_message_id: str | None = None
    stance: Stance | None = None
    created_at: AwareDatetime


class MessageRole(StrEnum):
    ASSISTANT = "assistant"
    HUMAN = "human"
    SYSTEM = "system"


class Message(BaseModel):
    id: str
    vehicle_id: str = VEHICLE_ID
    team: Team
    role: MessageRole
    author: str
    text: str
    notification_id: str | None = None
    proposal_id: str | None = None
    attachments: list[str] = []
    created_at: AwareDatetime


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Proposal(BaseModel):
    id: str
    vehicle_id: str = VEHICLE_ID
    team: Team
    kind: MailKind
    to_teams: list[Team]
    draft: str
    related_artifact_ids: list[str] = []
    thread_id: str
    status: ProposalStatus = ProposalStatus.PENDING
    decided_by: str | None = None
    decided_at: AwareDatetime | None = None
    created_at: AwareDatetime


class Notification(BaseModel):
    id: str
    vehicle_id: str = VEHICLE_ID
    team: Team
    origin_artifact_id: str | None
    impacted_ids: list[str]
    highlight_ids: list[str]
    cross_team_edges: list[tuple[str, str]]
    classification: Classification
    deliver_at: AwareDatetime | None
    reason: str
    created_at: AwareDatetime


class AgentRun(BaseModel):
    id: str
    vehicle_id: str = VEHICLE_ID
    team: Team
    state: Literal["running", "scheduled", "done"]
    title: str
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    detail: dict[str, Any] = {}


class Schedule(BaseModel):
    id: str
    vehicle_id: str = VEHICLE_ID
    team: Team
    due_at: AwareDatetime
    task: str
    payload: dict[str, Any] = {}


CONTAINER_MODELS: dict[str, type[BaseModel]] = {
    "artifacts": Artifact,
    "change_events": ChangeEvent,
    "test_runs": TestRun,
    "watches": Watch,
    "messages": Message,
    "proposals": Proposal,
    "agent_mail": AgentMail,
    "notifications": Notification,
    "agent_runs": AgentRun,
    "schedules": Schedule,
    "team_settings": TeamSettings,
}
