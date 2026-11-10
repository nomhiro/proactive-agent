import { formatTime } from "../api";
import type { AppState, Persona } from "../types";

type Props = {
  state: AppState | null;
  personas: Persona[];
  persona: string;
  onPersona: (id: string) => void;
  onToggleAdmin: () => void;
  adminOpen: boolean;
};

export function Header({ state, personas, persona, onPersona, onToggleAdmin, adminOpen }: Props) {
  return (
    <header className="header">
      <div className="brand">
        <span className="vehicle">架空SUV</span>
        <span className="subtitle">車両制御ソフトウェア開発</span>
      </div>
      {state?.release && (
        <div className="release">
          {state.release.id} まで あと <strong>{state.release.days_left}</strong> 日
        </div>
      )}
      <div className="clock" title="デモの仮想の時刻">
        {state ? formatTime(state.now) : ""}
      </div>
      <label className="persona">
        <span>誰として見るか</span>
        <select value={persona} onChange={(e) => onPersona(e.target.value)}>
          {personas.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name_ja}（{p.team_label}）
            </option>
          ))}
        </select>
      </label>
      <button className={adminOpen ? "admin-toggle active" : "admin-toggle"} onClick={onToggleAdmin}>
        デモの操作
      </button>
    </header>
  );
}
