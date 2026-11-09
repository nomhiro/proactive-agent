// BFF の呼び出し。エラーは BFF が返す日本語の理由（detail）をそのまま投げる

import type { AppState, MapData, Persona, ProposalDoc, Step } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    credentials: "same-origin",
  });
  if (!res.ok) {
    let detail = `エラーが起きました（${res.status}）`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* 本文が JSON でないときは既定の文 */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const q = (persona: string) => `persona=${encodeURIComponent(persona)}`;

export const api = {
  me: () => call<{ user: string; personas: Persona[] }>("/api/me"),
  map: () => call<MapData>("/api/map"),
  state: (persona: string) => call<AppState>(`/api/state?${q(persona)}`),
  negotiate: (persona: string) => call<{ url: string | null }>(`/api/negotiate?${q(persona)}`),
  chat: (persona: string, text: string) =>
    call<{ message_id: string }>("/api/chat", { method: "POST", body: JSON.stringify({ persona, text }) }),
  decide: (proposalId: string, persona: string, action: "approve" | "reject", draft?: string) =>
    call<ProposalDoc>(`/api/proposals/${encodeURIComponent(proposalId)}/decision`, {
      method: "POST",
      body: JSON.stringify({ persona, action, draft }),
    }),
  setProactivity: (persona: string, proactivity: string) =>
    call<{ proactivity: string }>("/api/settings", { method: "PUT", body: JSON.stringify({ persona, proactivity }) }),
  steps: () => call<{ steps: Step[]; now: string }>("/api/admin/steps"),
  next: () => call<Step>("/api/admin/next", { method: "POST" }),
  reset: () => call<{ ok: boolean }>("/api/admin/reset", { method: "POST" }),
  fileUrl: (fileId: string, persona: string) => `/api/files/${encodeURIComponent(fileId)}?${q(persona)}`,
};

const fmt = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : fmt.format(d);
}
