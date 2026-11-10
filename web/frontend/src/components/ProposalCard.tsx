import { useState } from "react";
import { api } from "../api";
import { TEAM_LABELS, type ProposalDoc } from "../types";

type Props = {
  proposal: ProposalDoc;
  persona: string;
  canDecide: boolean;
  people: Record<string, string>;
  onDone: () => void;
};

// 承認カード: 「送る / 直す / 今回は送らない」（設計書 5.1 節、決定 7）
export function ProposalCard({ proposal, persona, canDecide, people, onDone }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(proposal.draft);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const to = proposal.to_teams.map((t) => TEAM_LABELS[t] ?? t).join("、");

  async function decide(action: "approve" | "reject") {
    setSending(true);
    setError(null);
    try {
      await api.decide(proposal.id, persona, action, editing && action === "approve" ? draft : undefined);
      setEditing(false);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  const who = proposal.decided_by ? people[proposal.decided_by] ?? proposal.decided_by : "";
  return (
    <div className={`proposal ${proposal.status}`}>
      <div className="proposal-head">
        <span className="badge">承認待ちの下書き</span>
        <span>宛先: {to}</span>
      </div>
      {editing ? (
        <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={6} aria-label="下書きを直す" />
      ) : (
        <p className="draft">{proposal.draft}</p>
      )}
      {proposal.status === "pending" ? (
        canDecide ? (
          <div className="actions">
            <button className="primary" disabled={sending} onClick={() => decide("approve")}>
              送る
            </button>
            <button disabled={sending} onClick={() => setEditing(!editing)}>
              {editing ? "直すのをやめる" : "直す"}
            </button>
            <button disabled={sending} onClick={() => decide("reject")}>
              今回は送らない
            </button>
          </div>
        ) : (
          <div className="muted">このチームの人だけが決められます</div>
        )
      ) : (
        <div className="decided">
          {proposal.status === "approved" ? `送りました（${who}）` : `今回は送りませんでした（${who}）`}
        </div>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
