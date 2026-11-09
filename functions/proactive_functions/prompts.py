"""調査の依頼を、エージェントへの指示文（日本語）にする（Plan 3 決定 10）。

指示文に書くのは依頼の事実だけ。調べ方や知らせ方の判断は、エージェントの instructions とスキルに任せる。
"""

import json

from vehicle_core.constants import Team
from vehicle_core.models import AgentMail, ChangeEvent, Schedule
from vehicle_core.routing import InvestigationRequest

TRIGGER_LABELS = {
    "change": "開発データの変更",
    "test_run": "試験結果",
    "schedule": "定時の仕事",
    "mail": "エージェント間メール",
}
MORNING_TASKS = {"morning_digest", "morning_briefing"}
MAX_MAIL_BODY = 1000


def _impact_lines(req: InvestigationRequest) -> list[str]:
    imp = req.impact
    if imp is None:
        return []
    per_team = ", ".join(f"{t.value}: {len(ids)}" for t, ids in sorted(imp.impacted_by_team.items()))
    lines = [
        "影響の要約（trace_impact で確かめられる）:",
        f"- 影響を受けるデータ: {len(imp.impacted_ids)} 件（チームごと: {per_team or 'なし'}）",
        f"- 影響を受ける統合リリース: {', '.join(imp.affects_release_ids) or 'なし'}",
        f"- 安全要求に関わる: {'はい' if imp.touches_safety else 'いいえ'}",
    ]
    if imp.highlight_ids:
        lines.append(f"- 特に見るべきデータ: {', '.join(imp.highlight_ids)}")
    return lines


def _schedule_lines(schedules: list[Schedule]) -> list[str]:
    lines = []
    for s in schedules:
        payload = json.dumps(s.payload, ensure_ascii=False, sort_keys=True)
        lines.append(f"定時の仕事: {s.task}（予定 {s.id}、引数 {payload}）")
    return lines


def _value(v) -> str:
    return json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else f"「{v}」"


def _is_number(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _change_lines(changes: list[ChangeEvent], team: Team) -> list[str]:
    """変更の前と後。trace_impact はつながりから影響範囲を出すので、中身を見ないと誤字の修正でも知らせてしまう。

    数値が変わったときは investigate スキルの手順5を指す。スキルに書くだけでは、エージェントがこの手順を飛ばした
    （Azure 上での確認 2回目）。評価チームは自分で解析するので指さない。
    """
    if not changes:
        return []
    lines = ["変更の中身:"]
    for c in changes:
        lines += [f"- {c.artifact_id} の {f.path}: {_value(f.before)} → {_value(f.after)}" for f in c.changes]
    if not any(c.is_substantive for c in changes):
        lines.append("- 題名や説明文だけの変更（値や仕様の項目は変わっていない）")
    elif team != Team.EVALUATION and any(
            _is_number(f.before) and _is_number(f.after) for c in changes if c.is_substantive for f in c.changes):
        lines.append("- 数値の変更なので、investigate スキルの手順5のとおり、評価チームに analysis_request を送る")
    return lines


def _mail_lines(mails: list[AgentMail]) -> list[str]:
    """届いたメールの中身。list_mail を呼ばなくても、何を頼まれたか、誰の返答かがわかるようにする。"""
    if not mails:
        return []
    lines = ["メールの中身:"]
    for m in mails:
        extra = [f"thread {m.thread_id}"] + ([f"stance {m.stance.value}"] if m.stance else [])
        if m.related_artifact_ids:
            extra.append(f"関係するデータ: {', '.join(m.related_artifact_ids)}")
        lines.append(f"- {m.id}（{m.from_team.value} → {m.to_team.value} の {m.kind.value}、{'、'.join(extra)}）:")
        lines.append(f"  {m.body[:MAX_MAIL_BODY]}")
    return lines


def investigation_prompt(req: InvestigationRequest, run_id: str, schedules: list[Schedule],
                         changes: list[ChangeEvent] | None = None, mails: list[AgentMail] | None = None) -> str:
    morning = any(s.task in MORNING_TASKS for s in schedules)
    lines = [
        "調査の依頼です。",
        f"- 依頼 ID: {req.id}",
        f"- きっかけ: {TRIGGER_LABELS.get(req.trigger, req.trigger)}（{req.trigger}）",
        f"- 起点のデータ: {req.origin_artifact_id or 'なし'}",
        f"- 関係するデータ ID: {', '.join(req.source_ids) or 'なし'}",
    ]
    if req.matched_watch_ids:
        lines.append(f"- 一致した見張り: {', '.join(req.matched_watch_ids)}")
    lines.append(f"- 知らせ方の下限: {req.floor.value}（これより弱い知らせ方にはしない）")
    lines.append(f"- 作業記録: {run_id}")
    lines += _change_lines(changes or [], req.team)
    lines += _mail_lines(mails or [])
    lines += _impact_lines(req)
    lines += _schedule_lines(schedules)
    lines += ["", "手順:", "1. 最初に get_now を呼び、いまの時刻と、静かな時間帯かどうかを確かめる。"]
    if morning:
        lines.append("2. 朝のまとめは、ほかの道具より先に begin_morning_digest を呼ぶ。already_done が返ったら、何もせずに終える。")
    lines.append(f"{len(lines) - lines.index('手順:')}. 調査の最後に、finish_run を run_id=\"{run_id}\" と結果の要約で呼ぶ。")
    return "\n".join(lines)
