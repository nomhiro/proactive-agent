import { formatTime } from "../api";
import { TEAM_LABELS, type AppState } from "../types";

type Props = { state: AppState };

// アシスタントの作業（いま / 予定 / 完了）。設計書 7.9 節、決定 12
export function WorkPanel({ state }: Props) {
  const chief = state.team === "chief_engineer";
  const teamTag = (team: string) => (chief ? <span className="tag">{TEAM_LABELS[team] ?? team}</span> : null);
  const { now, planned, done } = state.work;
  return (
    <div className="work">
      <h3>アシスタントの作業</h3>
      <div className="work-columns">
        <div>
          <h4>いま</h4>
          {now.length === 0 && <div className="muted">なし</div>}
          {now.map((r) => (
            <div key={r.id} className="work-item running">
              {teamTag(r.team)}
              {r.title}
              <div className="time">{formatTime(r.started_at)} から</div>
            </div>
          ))}
        </div>
        <div>
          <h4>予定</h4>
          {planned.map((p, i) => (
            <div key={`${p.kind}-${i}`} className="work-item">
              {teamTag(p.team)}
              {p.title}
              <div className="time">{formatTime(p.at)}</div>
            </div>
          ))}
        </div>
        <div>
          <h4>完了</h4>
          {done.length === 0 && <div className="muted">なし</div>}
          {done.map((r) => (
            <details key={r.id} className="work-item">
              <summary>
                {teamTag(r.team)}
                {r.title}
                <span className="time"> {formatTime(r.finished_at)}</span>
              </summary>
              {r.summary && <div className="summary">{r.summary}</div>}
            </details>
          ))}
        </div>
      </div>
    </div>
  );
}
