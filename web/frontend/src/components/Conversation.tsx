import { useEffect, useRef, useState } from "react";
import { api, formatTime } from "../api";
import { TEAM_LABELS, type AppState, type MessageDoc } from "../types";
import { ProposalCard } from "./ProposalCard";

type Props = {
  state: AppState;
  persona: string;
  selectedNotification: string | null;
  onSelect: (notificationId: string | null) => void;
  onChanged: () => void;
};

function authorLabel(m: MessageDoc, state: AppState): string {
  if (m.role === "human") return state.people[m.author] ?? m.author;
  if (m.role === "system") return "お知らせ";
  return m.team === "chief_engineer" ? "車種統括エージェント" : `${TEAM_LABELS[m.team] ?? m.team}のアシスタント`;
}

export function Conversation({ state, persona, selectedNotification, onSelect, onChanged }: Props) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const count = state.messages.length;

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [count, persona]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setSending(true);
    setError(null);
    try {
      await api.chat(persona, text);
      setText("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  const priority = new Set(state.priority_message_ids);
  const render = (m: MessageDoc) => {
    const selectable = Boolean(m.notification_id && state.notifications[m.notification_id]);
    const selected = selectable && m.notification_id === selectedNotification;
    const proposal = m.proposal_id ? state.proposals[m.proposal_id] : undefined;
    return (
      <div
        key={m.id}
        className={`message ${m.role}${selectable ? " selectable" : ""}${selected ? " selected" : ""}`}
        onClick={() => selectable && onSelect(selected ? null : m.notification_id)}
      >
        <div className="meta">
          <span className="author">{authorLabel(m, state)}</span>
          <span className="time">{formatTime(m.created_at)}</span>
          {selectable && <span className="hint">{selected ? "マップで表示中" : "マップで見る"}</span>}
        </div>
        <div className="text">{m.text}</div>
        {m.attachments
          .filter((a) => a.startsWith("foundry-file:"))
          .map((a) => (
            <img key={a} className="attachment" alt="解析のグラフ" src={api.fileUrl(a.slice("foundry-file:".length), persona)} />
          ))}
        {proposal && (
          <div onClick={(e) => e.stopPropagation()}>
            <ProposalCard
              proposal={proposal}
              persona={persona}
              canDecide={proposal.team === state.team}
              people={state.people}
              onDone={onChanged}
            />
          </div>
        )}
      </div>
    );
  };

  const priorityMessages = state.messages.filter((m) => priority.has(m.id));
  return (
    <section className="pane conversation">
      <h2>会話（{state.team_label}）</h2>
      {priorityMessages.length > 0 && (
        <div className="priority">
          <h3>判断が必要なこと</h3>
          {priorityMessages.map(render)}
        </div>
      )}
      <div className="messages">
        {state.messages.length === 0 && <div className="muted">まだメッセージはありません</div>}
        {state.messages.filter((m) => !priority.has(m.id)).map(render)}
        <div ref={bottom} />
      </div>
      <form className="composer" onSubmit={send}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={state.chat_busy ? "返事を書いています…" : "アシスタントに話しかける（見張りや好みも頼めます）"}
          disabled={state.chat_busy || sending}
          rows={2}
          maxLength={2000}
        />
        <button className="primary" type="submit" disabled={state.chat_busy || sending || !text.trim()}>
          送る
        </button>
      </form>
      {error && <div className="error">{error}</div>}
    </section>
  );
}
