from datetime import datetime

from vehicle_core.constants import JST, VEHICLE_ID
from vehicle_core.impact import Graph, analyze_impact
from vehicle_core.seed import build_dataset

from proactive_web.scenario_checks import EXPECTATIONS, CheckContext, snapshot
from tests.helpers import MORNING, NIGHT, message, notification, run

GRAPH = Graph.from_artifacts(build_dataset().artifacts)
S1_IMPACT = analyze_impact(GRAPH, "SIG-BrkPedalPos").impacted_ids


class FakeMemory:
    def __init__(self, items=None):
        self.items = items or {}

    def list(self, team):
        return self.items.get(team, [])


def check(key, name):
    found = [c for c in EXPECTATIONS[key] if c.name == name]
    assert found, f"{key}: {name} がない（{[c.name for c in EXPECTATIONS[key]]}）"
    return found[0]


def passes(ctx, key, name) -> bool:
    return bool(check(key, name).predicate(ctx))


def ctx_for(store, before=None, memory=None):
    return CheckContext(store=store, memory=memory, before_ids=before if before is not None else snapshot(store))


def mail(id_, kind, frm, to, **extra):
    return {"id": id_, "vehicle_id": VEHICLE_ID, "thread_id": "th-1", "from_team": frm, "to_team": to,
            "kind": kind, "body": extra.pop("body", "本文"), "related_artifact_ids": [], "source_message_id": None,
            "stance": extra.pop("stance", None), "created_at": NIGHT.isoformat(), **extra}


def inv_run(store, id_, team, origin, state="done"):
    store.create("investigations", {"id": f"inv-{id_}", "vehicle_id": VEHICLE_ID, "team": team,
                                    "origin_artifact_id": origin, "status": "dispatched"})
    store.create("agent_runs", run(f"run-inv-inv-{id_}", team=team, state=state,
                                   detail={"investigation_id": f"inv-{id_}"}))


def test_every_check_has_name_and_positive_timeout():
    for key, checks in EXPECTATIONS.items():
        assert checks, key
        for c in checks:
            assert c.name and c.timeout_s > 0, (key, c.name)


def test_s1_change_expects_code_determined_impact_set(store):
    before = snapshot(store)
    store.create("notifications", notification(
        "n-1", origin="SIG-BrkPedalPos", impacted=S1_IMPACT, deliver_at="2026-11-18T08:00:00+09:00"))
    ctx = ctx_for(store, before)
    assert passes(ctx, "s1_signal_period#0", "通知の影響範囲がコードの計算と一致する")
    assert passes(ctx, "s1_signal_period#0", "起点 SIG-BrkPedalPos、notify_now、届けるのは 11/18 08:00 の未配達の通知がある")
    store.upsert("notifications", store.get("notifications", "n-1") | {"impacted_ids": ["MDL-MotorTq"]})
    assert not passes(ctx, "s1_signal_period#0", "通知の影響範囲がコードの計算と一致する")


def test_s1_change_expects_investigation_mails_and_proposal(store):
    before = snapshot(store)
    ctx = ctx_for(store, before)
    assert not passes(ctx, "s1_signal_period#0", "統合制御の調査の記録が done")
    inv_run(store, "s1", "integrated_control", "SIG-BrkPedalPos")
    assert passes(ctx, "s1_signal_period#0", "統合制御の調査の記録が done")
    store.create("agent_mail", mail("am-1", "analysis_request", "integrated_control", "evaluation"))
    assert not passes(ctx, "s1_signal_period#0", "評価に analysis_request、評価から analysis_result が届く")
    store.create("agent_mail", mail("am-2", "analysis_result", "evaluation", "integrated_control"))
    assert passes(ctx, "s1_signal_period#0", "評価に analysis_request、評価から analysis_result が届く")
    store.create("proposals", {"id": "prop-1", "vehicle_id": VEHICLE_ID, "team": "integrated_control",
                               "kind": "impact_notice", "to_teams": ["motor_control"], "status": "pending",
                               "draft": "d", "thread_id": "th-1", "created_at": NIGHT.isoformat()})
    assert passes(ctx, "s1_signal_period#0", "モーター制御宛ての impact_notice の下書き（pending）がある")


def test_s1_night_expects_no_visible_message_for_tanaka(store):
    before = snapshot(store)
    store.create("notifications", notification("n-1", delivered_at=None))
    store.create("messages", message("m-held", notification_id="n-1"))
    ctx = ctx_for(store, before)
    key, name = "s1_signal_period#0", "夜のあいだ田中の画面に新しいメッセージが出ない"
    assert check(key, name).final and passes(ctx, key, name)
    store.create("messages", message("m-loose"))  # 通知にひもづけずに話しかけた
    assert not passes(ctx, key, name)


def test_s1_morning_expects_delivered_and_message_mentioning_ids(store):
    store.create("notifications", notification("n-1", delivered_at=MORNING))
    store.create("messages", message("m-1", notification_id="n-1", proposal_id="prop-1",
                                     text="SIG-BrkPedalPos の変更で MDL-MotorTq に影響"))
    ctx = ctx_for(store)
    assert passes(ctx, "s1_signal_period#1", "s1 の通知が配達済み")
    assert passes(ctx, "s1_signal_period#1", "田中の画面に提案つきのメッセージがあり、SIG-BrkPedalPos と MDL-MotorTq に触れている")


def test_s1_sato_reply_expects_human_reply_with_exact_text(store):
    from vehicle_core.scenarios import SCENARIOS
    text = SCENARIOS["s1_signal_period"].steps[3].text
    before = snapshot(store)
    ctx = ctx_for(store, before)
    store.create("agent_mail", mail("am-1", "human_reply", "motor_control", "integrated_control",
                                    stance="cannot", body=text + "。"))
    name = "モーター制御から統合制御へ human_reply（stance cannot、本文は佐藤の発言そのもの）"
    assert not passes(ctx, "s1_signal_period#3", name)
    store.create("agent_mail", mail("am-2", "human_reply", "motor_control", "integrated_control",
                                    stance="cannot", body=text))
    assert passes(ctx, "s1_signal_period#3", name)


def test_s1_tanaka_reply_expects_escalation_to_chief(store):
    ctx = ctx_for(store)
    assert not passes(ctx, "s1_signal_period#4", "統括に escalation が届く")
    store.create("agent_mail", mail("am-1", "escalation", "integrated_control", "chief_engineer"))
    assert passes(ctx, "s1_signal_period#4", "統括に escalation が届く")
    name = "高橋の画面に notify_now の通知にひもづくメッセージがあり、MDL-MotorTq に触れている"
    store.create("notifications", notification("n-ce", team="chief_engineer", delivered_at=MORNING))
    store.create("messages", message("m-ce", team="chief_engineer", notification_id="n-ce", text="MDL-MotorTq の判断"))
    assert passes(ctx, "s1_signal_period#4", name)


def test_s5_watch_and_memory(store):
    ctx = ctx_for(store, memory=FakeMemory())
    assert not passes(ctx, "s5_watch_memory#0", "統合制御に test_failure_streak（regen_coord、すぐ）の見張りがある")
    store.create("watches", {"id": "w-1", "vehicle_id": VEHICLE_ID, "team": "integrated_control",
                             "kind": "test_failure_streak", "feature": "regen_coord", "delivery": "immediate",
                             "description": "d", "created_by": "tanaka", "created_at": MORNING.isoformat()})
    assert passes(ctx, "s5_watch_memory#0", "統合制御に test_failure_streak（regen_coord、すぐ）の見張りがある")
    mem = FakeMemory({"integrated_control": [{"id": "m1", "text": "連絡は朝にまとめてほしい"}]})
    assert passes(ctx_for(store, memory=mem), "s5_watch_memory#1", "統合制御の記憶に「朝」の好みがある")
    assert not passes(ctx_for(store, memory=mem), "s5_watch_memory#2", "統合制御の記憶から「朝」の好みが消える")
    assert passes(ctx_for(store, memory=FakeMemory()), "s5_watch_memory#2", "統合制御の記憶から「朝」の好みが消える")


def test_s2_expects_immediate_delivery(store):
    before = snapshot(store)
    ctx = ctx_for(store, before)
    inv_run(store, "s2", "integrated_control", "TC-HILS-031")
    assert passes(ctx, "s2_hils_streak#2", "統合制御の調査の記録が done")
    store.create("notifications", notification("n-2", origin="TC-HILS-031", delivered_at=MORNING))
    assert passes(ctx, "s2_hils_streak#2", "統合制御に配達済みの notify_now の通知がある")


def test_s0_noise_expects_no_new_notification_or_message(store):
    before = snapshot(store)
    ctx = ctx_for(store, before)
    inv_run(store, "s0", "integrated_control", "SPEC-BRK-04")
    assert passes(ctx, "s0_noise#0", "統合制御の調査の記録が done")
    quiet = "起点 SPEC-BRK-04 の silent 以外の通知がない"
    silent_screen = "田中の画面に新しいメッセージがない"
    assert check("s0_noise#0", quiet).final and check("s0_noise#0", silent_screen).final
    store.create("notifications", notification("n-s", origin="SPEC-BRK-04", classification="silent",
                                               delivered_at=MORNING))
    assert passes(ctx, "s0_noise#0", quiet) and passes(ctx, "s0_noise#0", silent_screen)
    store.create("notifications", notification("n-d", origin="SPEC-BRK-04", classification="digest"))
    store.create("messages", message("m-1", text="誤字を直しました"))
    assert not passes(ctx, "s0_noise#0", quiet) and not passes(ctx, "s0_noise#0", silent_screen)


def test_s3_expects_four_morning_runs(store):
    ctx = ctx_for(store)
    name = "4体の朝のまとめ（run-morning-…-20261119）が done"
    for team in ["chief_engineer", "integrated_control", "motor_control"]:
        store.create("agent_runs", run(f"run-morning-{team}-20261119", team=team, state="done"))
    assert not passes(ctx, "s3_morning#0", name)
    store.create("agent_runs", run("run-morning-evaluation-20261119", team="evaluation", state="done"))
    assert passes(ctx, "s3_morning#0", name)


def test_s4_expects_release_gap_message(store):
    before = snapshot(store)
    ctx = ctx_for(store, before)
    sch = store.get("schedules", "sch-release-gap-R3")
    store.upsert("schedules", sch | {"done_at": datetime(2026, 11, 23, 8, 0, tzinfo=JST).isoformat()})
    assert passes(ctx, "s4_release_gap#0", "sch-release-gap-R3 が実行済み")
    store.create("messages", message("m-1", team="chief_engineer", text="R3 の抜け漏れ: 未検証の要求 7 件"))
    assert passes(ctx, "s4_release_gap#0", "統括に R3 に触れたメッセージがある")
