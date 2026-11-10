"""シナリオを1手ずつ進める（決定 17〜19、設計書 5.3 節）。画面の「デモの操作」と scripts/scenario.py が使う。

- SCENARIO_ORDER の全シナリオの手順を1列に並べ、system/scenario_progress の next_index で次の手を覚える
- 「次へ」は、前提を確かめる → 時計を手順の時刻まで進める（戻さない）→ 手順を行う → next_index を進める
- 前提が揃っていなければ、時計も進み具合も変えずに StepNotReady
- 時計の手順は、調査が終わるまで進めない（夜の調査の途中で朝にすると、昼の時刻で通知が記録されてしまう）。
  「終わった」はデータから決める: 直前の時計の手順より後に流した変更イベント・試験結果と、すべてのエージェント間
  メールについて、Functions と同じ振り分け（vehicle_core.routing、handlers.mail_request）で調査依頼の ID を
  求め、その依頼がまだない／pending／dispatched なのに作業記録 run-inv-<ID> が done でない、のどれかなら待つ
  （変更フィードのトリガーが動く前と、起動の直前の隙間をふさぐ）
- 承認の手順は、発表者が画面で先に承認していれば、その提案で足りないメールを揃えて済ませる
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from proactive_functions.clock import StoredClock, set_virtual_now
from proactive_functions.docs import models
from proactive_functions.handlers import load_graph, mail_request
from proactive_functions.seeding import seed_store
from proactive_functions.store import Conflict, NotFound, Store
from vehicle_core.changes import apply_changes
from vehicle_core.clock import crossed_morning, to_jst
from vehicle_core.constants import AGENT_TEAMS, DIGEST_TIME, JST, VEHICLE_ID
from vehicle_core.models import AgentMail, MailKind, ProposalStatus, TestRun, Watch
from vehicle_core.routing import route_change, route_test_run
from vehicle_core.scenarios import (
    SCENARIO_ORDER,
    SCENARIOS,
    Scenario,
    ScenarioStep,
    StepKind,
)
from vehicle_core.seed import build_dataset

from .chat import ChatBusy, ChatService
from .personas import PERSONAS
from .proposals import decide_proposal

PROGRESS_CONTAINER = "system"
PROGRESS_ID = "scenario_progress"
PEOPLE: dict[str, str] = {p.id: p.name_ja for p in build_dataset().people}
LONG_VALUE = 20
MORNING_WAIT = timedelta(minutes=10)  # 実時間。朝のまとめが起動しなかったとき、デモが止まり続けないように
DISPATCH_STALE = timedelta(minutes=15)  # 起動の印を付けたまま作業記録ができない依頼は、止まったものとみなす


class StepNotReady(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _flat() -> list[tuple[Scenario, ScenarioStep]]:
    return [(SCENARIOS[sid], step) for sid in SCENARIO_ORDER for step in SCENARIOS[sid].steps]


def _short(value) -> bool:
    return len(str(value)) <= LONG_VALUE


def step_summary(step: ScenarioStep, people: dict[str, str]) -> str:
    at = f"{to_jst(step.at):%m/%d %H:%M}"
    if step.kind == StepKind.CHANGE and step.change:
        c = step.change.changes[0]
        who = people.get(step.change.changed_by, step.change.changed_by)
        if _short(c.before) and _short(c.after):
            return f"{at} {who}が {step.change.artifact_id} の {c.path} を {c.before} から {c.after} に変える"
        return f"{at} {who}が {step.change.artifact_id} の {c.path} を直す"
    if step.kind == StepKind.SET_CLOCK:
        return f"{at} まで時計を進める"
    if step.kind == StepKind.TEST_RUN and step.test_run:
        return f"{at} {step.test_run.testcase_id} の試験結果（{step.test_run.result}）が入る"
    who = people.get(step.person_id or "", step.person_id or "")
    if step.kind == StepKind.APPROVE:
        return f"{at} {who}が承認待ちの影響の連絡を送る"
    return f"{at} {who}: {step.text}"


class _System:
    def __init__(self, now: Callable[[], datetime]) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now()


def _real_now() -> datetime:
    return datetime.now(JST)


class ScenarioRunner:
    def __init__(self, store: Store, chat: ChatService | None, system_now: Callable[[], datetime] = _real_now) -> None:
        self.store = store
        self.chat = chat
        self.system_now = system_now

    # --- 進み具合 ---------------------------------------------------------------

    def _progress(self) -> tuple[dict | None, int]:
        doc = self.store.get(PROGRESS_CONTAINER, PROGRESS_ID)
        return doc, int(doc["next_index"]) if doc else 0

    def _save_progress(self, doc: dict | None, next_index: int) -> None:
        fresh = {"id": PROGRESS_ID, "vehicle_id": VEHICLE_ID, "next_index": next_index}
        try:
            if doc is None:
                self.store.create(PROGRESS_CONTAINER, fresh)
            else:
                self.store.replace(PROGRESS_CONTAINER, doc | fresh, etag=doc["_etag"])
        except (Conflict, NotFound):
            raise StepNotReady("ほかの操作と重なりました。手順の一覧を読み直してください") from None

    def steps(self) -> list[dict]:
        _, next_index = self._progress()
        return [{"index": i, "scenario_id": sc.id, "scenario_title": sc.title_ja, "kind": step.kind.value,
                 "at": to_jst(step.at).isoformat(), "summary": step_summary(step, PEOPLE), "done": i < next_index}
                for i, (sc, step) in enumerate(_flat())]

    # --- 前提 -------------------------------------------------------------------

    def _expected_investigations(self, index: int) -> list[str]:
        """直前の時計の手順より後の変更・試験結果と、すべてのメールから、作られるはずの調査依頼の ID。"""
        graph = load_graph(self.store)
        watches = models(self.store.query("watches"), Watch)
        ids: list[str] = []
        for _, step in reversed(_flat()[:index]):
            if step.kind == StepKind.SET_CLOCK:
                break
            if step.kind == StepKind.CHANGE and step.change:
                ids += [r.id for r in route_change(step.change, graph, watches)]
            if step.kind == StepKind.TEST_RUN and step.test_run:
                new = step.test_run
                history = [r for r in models(self.store.query("test_runs", {"feature": new.feature}), TestRun)
                           if r.id != new.id and r.executed_at <= new.executed_at]  # トリガーが見た時点の履歴
                ids += [r.id for r in route_test_run(new, history, graph, watches)]
        for mail in models(self.store.query("agent_mail"), AgentMail, skip_seed=True):
            request = mail_request(mail)
            if request is not None:
                ids.append(request.id)
        return ids

    def _investigation_unfinished(self, inv_id: str, seen: frozenset[str] = frozenset()) -> bool:
        doc = self.store.get("investigations", inv_id)
        if doc is None:
            return True  # 変更フィードのトリガーがまだ依頼を作っていない
        status = doc.get("status")
        if status == "pending":
            return True
        if status == "merged":
            target = doc.get("merged_into")
            return bool(target) and target not in seen and self._investigation_unfinished(target, seen | {inv_id})
        if status == "dispatched":
            run = self.store.get("agent_runs", f"run-inv-{inv_id}")
            if run is None:
                dispatched_at = doc.get("dispatched_at")
                return not (dispatched_at and self._virtual_now() - to_jst(datetime.fromisoformat(dispatched_at))
                            > DISPATCH_STALE)
            return run.get("state") != "done"
        return False  # failed

    def _unfinished_investigation(self, index: int) -> str | None:
        pending = self.store.query("investigations", {"status": "pending"})
        if pending:
            return pending[0]["id"]
        for inv_id in self._expected_investigations(index):
            if self._investigation_unfinished(inv_id):
                return inv_id
        for r in self.store.query("agent_runs", {"state": "running"}):
            if (r.get("detail") or {}).get("kind") != "chat":
                return r["id"]
        return None

    def _unfinished_morning(self, index: int) -> str | None:
        """直前の時計の手順が朝を越えていたら、その朝の4体のまとめが終わるまで待つ。「次へ」を続けて押すと、tick が
        朝のまとめを起動する前に次の朝まで進み、11/19 の朝が飛んだ（画面での確認）。時計を進めてから実時間で
        MORNING_WAIT を過ぎたら待たない。"""
        flat = _flat()
        j = next((k for k in range(index - 1, 0, -1) if flat[k][1].kind == StepKind.SET_CLOCK), None)
        if j is None or not crossed_morning(flat[j - 1][1].at, flat[j][1].at):
            return None
        clock = self.store.get("system", "clock") or {}
        updated = clock.get("updated_at")
        if updated and self.system_now() - to_jst(datetime.fromisoformat(updated)) >= MORNING_WAIT:
            return None
        at = to_jst(flat[j][1].at)
        day = at.date() if at.time() >= DIGEST_TIME else at.date() - timedelta(days=1)
        for team in AGENT_TEAMS:
            run_id = f"run-morning-{team.value}-{day:%Y%m%d}"
            doc = self.store.get("agent_runs", run_id)
            if doc is None or doc.get("state") != "done":
                return run_id
        return None

    def _notices(self, team: str, status: ProposalStatus) -> list[dict]:
        found = [p for p in self.store.query("proposals", {"team": team, "status": status.value})
                 if p.get("kind") == MailKind.IMPACT_NOTICE.value]
        return sorted(found, key=lambda p: to_jst(datetime.fromisoformat(p["created_at"])))

    def _notice_to_approve(self, team: str) -> dict | None:
        """いちばん古い承認待ち。なければ、発表者が画面で先に承認したもの（足りないメールを揃える）。"""
        pending = self._notices(team, ProposalStatus.PENDING)
        if pending:
            return pending[0]
        approved = self._notices(team, ProposalStatus.APPROVED)
        return approved[-1] if approved else None

    def _check(self, step: ScenarioStep, index: int) -> dict | None:
        if step.kind == StepKind.SET_CLOCK:
            busy = self._unfinished_investigation(index)
            if busy:
                raise StepNotReady(f"調査が終わっていません（{busy}）。終わってから時計を進めます")
            morning = self._unfinished_morning(index)
            if morning:
                raise StepNotReady(f"朝のまとめが終わっていません（{morning}）。終わってから時計を進めます")
        if step.kind == StepKind.APPROVE:
            proposal = self._notice_to_approve(step.team.value)
            if proposal is None:
                raise StepNotReady("承認待ちの影響の連絡がまだありません。アシスタントの調査が終わるのを待ってください")
            return proposal
        if step.kind == StepKind.HUMAN_SAYS:
            if self.chat is None:
                raise StepNotReady("チャットが設定されていません")
            if self.chat.busy(step.team):
                raise StepNotReady("アシスタントがまだ前の返事を書いています")
        return None

    # --- 手順 -------------------------------------------------------------------

    def _virtual_now(self) -> datetime:
        return StoredClock(self.store, _System(self.system_now)).now()

    def _advance_clock(self, at: datetime) -> None:
        if self._virtual_now() < to_jst(at):
            set_virtual_now(self.store, at, self.system_now())

    def _apply_change(self, step: ScenarioStep) -> None:
        event = step.change
        try:
            self.store.create("change_events", event.model_dump(mode="json"))
        except Conflict:
            pass  # 前回の途中まで行った分
        for _ in range(3):
            doc = self.store.get("artifacts", event.artifact_id)
            if doc is None:
                return
            try:
                self.store.replace("artifacts", apply_changes(doc, event.changes, step.at), etag=doc["_etag"])
                return
            except (Conflict, NotFound):
                continue

    def next(self) -> dict:
        doc, index = self._progress()
        flat = _flat()
        if index >= len(flat):
            raise StepNotReady("シナリオはすべて終わりました。最初からやり直すときは「デモを最初からやり直す」を使ってください")
        _, step = flat[index]
        proposal = self._check(step, index)
        self._advance_clock(step.at)
        if step.kind == StepKind.CHANGE:
            self._apply_change(step)
        elif step.kind == StepKind.TEST_RUN:
            try:
                self.store.create("test_runs", step.test_run.model_dump(mode="json"))
            except Conflict:
                pass
        elif step.kind == StepKind.APPROVE:
            decide_proposal(self.store, proposal["id"], PERSONAS[step.person_id], "approve", None, self._virtual_now())
        elif step.kind == StepKind.HUMAN_SAYS:
            try:
                self.chat.send(PERSONAS[step.person_id], step.text)
            except ChatBusy as e:
                raise StepNotReady(str(e)) from None
        self._save_progress(doc, index + 1)
        return self.steps()[index]

    def reset(self) -> None:
        """Azure 上のデモのデータを消して作り直す（system ごと消えるので、進み具合も最初に戻る）。"""
        seed_store(self.store, reset=True, system_now=self.system_now())
