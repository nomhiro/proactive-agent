// 影響マップの光り方（決定 14）。描画から切り離した純粋な関数

import type { MapNode, NotificationDoc } from "./types";

export type Selection = {
  origin: string | null;
  impacted: Set<string>;
  highlight: Set<string>;
  cross: Set<string>; // "上流->下流"
};

export type ViewMode = { team: string; chief: boolean };

export type NodeTone = "origin" | "impacted" | "context" | "dim" | "own" | "other" | "even";
export type EdgeTone = "cross" | "dim" | "normal";

export const edgeKey = (source: string, target: string) => `${source}->${target}`;

export function selectionFrom(n: NotificationDoc): Selection {
  return {
    origin: n.origin_artifact_id,
    impacted: new Set(n.impacted_ids),
    highlight: new Set([...n.highlight_ids, ...n.impacted_ids, ...(n.origin_artifact_id ? [n.origin_artifact_id] : [])]),
    cross: new Set(n.cross_team_edges.map(([s, t]) => edgeKey(s, t))),
  };
}

export function nodeTone(id: string, group: string | null, sel: Selection | null, view: ViewMode): NodeTone {
  if (sel) {
    if (sel.origin === id) return "origin";
    if (sel.impacted.has(id)) return "impacted";
    if (sel.highlight.has(id)) return "context";
    return "dim";
  }
  if (view.chief) return "even";
  return group === null || group === view.team ? "own" : "other";
}

export function edgeTone(source: string, target: string, sel: Selection | null): EdgeTone {
  if (!sel) return "normal";
  if (sel.cross.has(edgeKey(source, target))) return "cross";
  return sel.highlight.has(source) && sel.highlight.has(target) ? "normal" : "dim";
}

export function visibleNodes(nodes: MapNode[], collapsed: Set<string>): MapNode[] {
  return nodes.filter((n) => n.type === "domain" || n.group === null || !collapsed.has(n.group));
}

export function compactRows(nodes: MapNode[]): MapNode[] {
  const byColumn = new Map<number, MapNode[]>();
  for (const n of nodes) byColumn.set(n.column, [...(byColumn.get(n.column) ?? []), n]);
  const out: MapNode[] = [];
  for (const column of [...byColumn.keys()].sort((a, b) => a - b)) {
    const sorted = [...(byColumn.get(column) ?? [])].sort((a, b) => a.row - b.row);
    sorted.forEach((n, row) => out.push({ ...n, row }));
  }
  return out;
}
