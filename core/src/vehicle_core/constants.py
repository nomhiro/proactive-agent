"""車種、チーム、時間帯など、全体で共有する定数。"""

from datetime import time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

VEHICLE_ID: str = "kakuu-suv"
JST = ZoneInfo("Asia/Tokyo")


class Team(StrEnum):
    CHIEF_ENGINEER = "chief_engineer"
    INTEGRATED_CONTROL = "integrated_control"
    MOTOR_CONTROL = "motor_control"
    BATTERY_CONTROL = "battery_control"
    EVALUATION = "evaluation"
    SOFTWARE_INTEGRATION = "software_integration"
    FUNCTIONAL_SAFETY = "functional_safety"


# アシスタントがいるチーム（設計書 4.3 節）
AGENT_TEAMS: frozenset[Team] = frozenset(
    {Team.CHIEF_ENGINEER, Team.INTEGRATED_CONTROL, Team.MOTOR_CONTROL, Team.EVALUATION}
)

TEAM_LABELS_JA: dict[Team, str] = {
    Team.CHIEF_ENGINEER: "車種統括",
    Team.INTEGRATED_CONTROL: "車両統合制御",
    Team.MOTOR_CONTROL: "モーター制御",
    Team.BATTERY_CONTROL: "電池制御",
    Team.EVALUATION: "評価",
    Team.SOFTWARE_INTEGRATION: "ソフト統合",
    Team.FUNCTIONAL_SAFETY: "機能安全",
}

# 連続する変更を1件にまとめる窓
DEBOUNCE_WINDOW = timedelta(seconds=180)
# 影響の連絡に人が返事をする期限。過ぎたらチーフエンジニアに上げる
REPLY_DEADLINE = timedelta(hours=48)
# 静かな時間帯（20:00 以上〜08:00 未満）
QUIET_START = time(20, 0)
QUIET_END = time(8, 0)
# まとめて知らせる時刻
DIGEST_TIME = time(8, 0)


def agent_name(team: Team) -> str:
    """Foundry のエージェント名（例: asst-integrated-control）。アシスタントのいないチームは ValueError。"""
    if team not in AGENT_TEAMS:
        raise ValueError(f"{team} にはアシスタントがいません")
    return "asst-" + team.value.replace("_", "-")
