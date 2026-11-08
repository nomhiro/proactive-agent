"""agents/ の指示文とスキルの決まり（設計書 4、7.4〜7.6、7.11 節）を確かめる。"""

import re
import sys
from pathlib import Path

from proactive_functions.mcp.server import build_registry

AGENTS = Path(__file__).resolve().parents[2] / "agents"
TEAMS = ["chief_engineer", "integrated_control", "motor_control", "evaluation"]
SKILLS = ["investigate", "notify-decision", "analysis", "drafting"]
# harness に組み込まれた道具（MCP サーバーの道具ではない）
HARNESS_TOOLS = {"upload_file_from_workspace_to_foundry_project"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "frontmatter がない"
    return dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)


def content_files() -> list[Path]:
    return [*(AGENTS / "instructions").glob("*.md"), *(AGENTS / "skills").glob("*/SKILL.md"), AGENTS / "routines.md"]


def test_instruction_files_exist_for_every_agent_team():
    assert sorted(p.stem for p in (AGENTS / "instructions").glob("*.md")) == sorted(TEAMS)


def test_every_instruction_requires_get_now_and_forbids_web():
    for t in TEAMS:
        text = read(AGENTS / "instructions" / f"{t}.md")
        assert "get_now" in text and "Web 取得" in text, t
        assert "サブエージェント" in text, t


def test_every_instruction_forbids_promising_on_behalf_of_team():
    for t in TEAMS:
        assert "約束しない" in read(AGENTS / "instructions" / f"{t}.md"), t


def test_skills_have_frontmatter_name_and_description():
    for name in SKILLS:
        fm = frontmatter(read(AGENTS / "skills" / name / "SKILL.md"))
        assert fm["name"].strip() == name
        assert len(fm["description"].strip()) >= 10


def test_routines_start_with_begin_morning_digest():
    text = read(AGENTS / "routines.md")
    sections = re.split(r"^## ", text, flags=re.M)[1:]
    assert sorted(s.splitlines()[0].strip() for s in sections) == ["chief_engineer", "team"]
    for s in sections:
        assert "begin_morning_digest" in s and "already_done" in s


def test_chief_asks_other_teams_with_a2a():  # 決定 15 は a2a
    text = read(AGENTS / "instructions" / "chief_engineer.md")
    assert "A2A" in text


def test_analysis_skill_installs_libraries_and_uploads_chart():  # 決定 14 は foundry-files
    text = read(AGENTS / "skills" / "analysis" / "SKILL.md")
    assert "pip install numpy scipy matplotlib" in text
    assert "upload_file_from_workspace_to_foundry_project" in text and "foundry-file:" in text
    assert "regen_model.py" in text


def test_tool_names_in_content_exist_in_registry():
    known = {t["name"] for t in build_registry().list()} | HARNESS_TOOLS
    for path in content_files():
        for name in re.findall(r"`([a-z][a-z0-9_]+)`", read(path)):
            if "_" not in name:
                continue  # 単語（`impact_notice` の種類名などは下で許す）
            assert name in known or name in KNOWN_NON_TOOLS, f"{path.name}: {name}"


# 道具名ではないが `` で書いてよい語（メールの種類、分類、状態、引数の名前）
KNOWN_NON_TOOLS = {
    "impact_notice", "analysis_request", "analysis_result", "human_reply", "notify_now", "already_done",
    "run_id", "item_id", "release_gap_check", "in_quiet_hours", "regen_model",
}


def test_regen_model_reproduces_scenario_delay():
    sys.path.insert(0, str(AGENTS / "skills" / "analysis"))
    from regen_model import step_delay_ms
    delta = step_delay_ms(20) - step_delay_ms(10)
    assert 12 <= delta <= 18  # 設計書 7.6 節: 約 15ms


def test_routines_close_the_run_from_begin_morning_digest():
    # begin_morning_digest が作業記録（run-morning-…）を作るので、別の start_run で始めない
    text = read(AGENTS / "routines.md")
    for s in re.split(r"^## ", text, flags=re.M)[1:]:
        assert "`start_run`" not in s and "`finish_run`" in s and "run_id" in s
