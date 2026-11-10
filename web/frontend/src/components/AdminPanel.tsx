import { useCallback, useEffect, useState } from "react";
import { api, formatTime } from "../api";
import type { Step } from "../types";

type Props = { onChanged: () => void };

// デモの操作（決定 17）。ブラウザの確認ダイアログは使わず、画面の中で確かめる
export function AdminPanel({ onChanged }: Props) {
  const [steps, setSteps] = useState<Step[]>([]);
  const [now, setNow] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await api.steps();
      setSteps(body.steps);
      setNow(body.now);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(action: () => Promise<string>) {
    setBusy(true);
    setMessage(null);
    try {
      setMessage(await action());
      onChanged();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      load();
    }
  }

  const next = steps.find((s) => !s.done);
  return (
    <aside className="admin">
      <div className="admin-head">
        <h2>デモの操作</h2>
        <span className="muted">仮想の時刻 {formatTime(now)}</span>
      </div>
      <div className="admin-actions">
        <button className="primary" disabled={busy || !next} onClick={() => run(async () => `行いました: ${(await api.next()).summary}`)}>
          次へ{next ? `（${next.summary}）` : ""}
        </button>
        {confirmReset ? (
          <span className="confirm">
            Azure 上のデモのデータを消して作り直します。
            <button
              className="danger"
              disabled={busy}
              onClick={() => {
                setConfirmReset(false);
                run(async () => {
                  await api.reset();
                  return "デモを最初からやり直しました";
                });
              }}
            >
              作り直す
            </button>
            <button onClick={() => setConfirmReset(false)}>やめる</button>
          </span>
        ) : (
          <button disabled={busy} onClick={() => setConfirmReset(true)}>
            デモを最初からやり直す
          </button>
        )}
      </div>
      {message && <div className="admin-message">{message}</div>}
      <ol className="steps">
        {steps.map((s, i) => (
          <li key={s.index} className={s.done ? "done" : s === next ? "next" : ""}>
            {(i === 0 || steps[i - 1].scenario_id !== s.scenario_id) && <div className="scenario">{s.scenario_title}</div>}
            <span className="mark">{s.done ? "済" : s === next ? "次" : ""}</span>
            {s.summary}
          </li>
        ))}
      </ol>
    </aside>
  );
}
