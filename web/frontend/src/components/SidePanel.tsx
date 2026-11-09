import { useState } from "react";
import { api } from "../api";
import type { AppState } from "../types";

const PROACTIVITY = [
  { value: "off", label: "止める" },
  { value: "important_only", label: "重要だけ" },
  { value: "normal", label: "ふつう" },
  { value: "frequent", label: "こまめに" },
];

type Props = { state: AppState; persona: string; onChanged: () => void };

// 見張りと設定（設計書 5.1 節の右の区画）
export function SidePanel({ state, persona, onChanged }: Props) {
  const [error, setError] = useState<string | null>(null);

  async function change(value: string) {
    setError(null);
    try {
      await api.setProactivity(persona, value);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section className="pane side">
      <h2>見張りと設定</h2>
      <h3>見張っていること</h3>
      {state.watches.length === 0 && <div className="muted">まだありません</div>}
      <ul className="list">
        {state.watches.map((w) => (
          <li key={w.id}>
            {w.description}
            <span className="tag">{w.delivery === "immediate" ? "すぐ" : "朝まとめて"}</span>
          </li>
        ))}
      </ul>
      <h3>話しかける頻度</h3>
      <div className="segmented" role="radiogroup" aria-label="話しかける頻度">
        {PROACTIVITY.map((p) => (
          <button
            key={p.value}
            role="radio"
            aria-checked={state.settings.proactivity === p.value}
            className={state.settings.proactivity === p.value ? "active" : ""}
            onClick={() => change(p.value)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="muted small">
        静かな時間帯: {state.settings.quiet_start.slice(0, 5)}〜{state.settings.quiet_end.slice(0, 5)}
      </div>
      <h3>覚えていること</h3>
      {state.memories.length === 0 && <div className="muted">まだありません</div>}
      <ul className="list">
        {state.memories.map((m) => (
          <li key={m.id}>{m.text}</li>
        ))}
      </ul>
      <p className="muted small">見張りと覚えることの追加・削除は、会話で頼めます（「〜が落ちたらすぐ教えて」「さっきの好みは忘れて」）。</p>
      {error && <div className="error">{error}</div>}
    </section>
  );
}
