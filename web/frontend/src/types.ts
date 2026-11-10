// BFF（proactive_web）が返す形。/api/state は決定 10、/api/map は決定 13 の形

export type Persona = { id: string; name_ja: string; team: string; team_label: string; role: string };

export type MessageDoc = {
  id: string;
  team: string;
  role: "assistant" | "human" | "system";
  author: string;
  text: string;
  notification_id: string | null;
  proposal_id: string | null;
  attachments: string[];
  created_at: string;
};

export type ProposalDoc = {
  id: string;
  team: string;
  kind: string;
  to_teams: string[];
  draft: string;
  related_artifact_ids: string[];
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
};

export type NotificationDoc = {
  id: string;
  team: string;
  origin_artifact_id: string | null;
  impacted_ids: string[];
  highlight_ids: string[];
  cross_team_edges: [string, string][];
  classification: "silent" | "digest" | "notify_now";
  reason: string;
  created_at: string;
  delivered_at: string | null;
};

export type RunView = {
  id: string;
  team: string;
  title: string;
  state: string;
  started_at: string | null;
  finished_at: string | null;
  summary: string | null;
};

export type PlanItem = { kind: "run" | "schedule" | "routine"; team: string; title: string; at: string };

export type WatchDoc = { id: string; description: string; delivery: "immediate" | "digest"; created_by: string };

export type AppState = {
  now: string;
  release: { id: string; due_date: string; days_left: number } | null;
  persona: Persona;
  team: string;
  team_label: string;
  people: Record<string, string>;
  messages: MessageDoc[];
  priority_message_ids: string[];
  proposals: Record<string, ProposalDoc>;
  notifications: Record<string, NotificationDoc>;
  work: { now: RunView[]; planned: PlanItem[]; done: RunView[] };
  watches: WatchDoc[];
  memories: { id: string; text: string }[];
  settings: { proactivity: string; quiet_start: string; quiet_end: string };
  chat_busy: boolean;
};

export type MapNode = {
  id: string;
  label: string;
  type: string;
  column: number;
  row: number;
  group: string | null;
};

export type MapData = {
  nodes: MapNode[];
  edges: { source: string; target: string; cross_team: boolean }[];
  groups: { team: string; label: string; has_assistant: boolean }[];
};

export type Step = {
  index: number;
  scenario_id: string;
  scenario_title: string;
  kind: string;
  at: string;
  summary: string;
  done: boolean;
};

export const TEAM_LABELS: Record<string, string> = {
  chief_engineer: "車種統括",
  integrated_control: "車両統合制御",
  motor_control: "モーター制御",
  battery_control: "電池制御",
  evaluation: "評価",
  software_integration: "ソフト統合",
  functional_safety: "機能安全",
};
