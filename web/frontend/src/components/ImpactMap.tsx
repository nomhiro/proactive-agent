import { useMemo, useState } from "react";
import { compactRows, edgeTone, nodeTone, visibleNodes, type Selection, type ViewMode } from "../mapView";
import type { MapData, MapNode } from "../types";

const COLUMN_TITLES = ["車種", "領域", "要求", "仕様・信号", "モデル", "テスト"];
const COL_W = 118;
const NODE_W = 100;
const NODE_H = 22;
const ROW_H = 28;
const TOP = 34;
const LEFT = 8;

type Props = { map: MapData; selection: Selection | null; view: ViewMode };

const x = (n: MapNode) => LEFT + n.column * COL_W;
const y = (n: MapNode) => TOP + n.row * ROW_H;

// 左から右へ流れる影響マップ（設計書 5.1 節、決定 13・14）
export function ImpactMap({ map, selection, view }: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const nodes = useMemo(() => compactRows(visibleNodes(map.nodes, collapsed)), [map, collapsed]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const assistant = useMemo(() => new Map(map.groups.map((g) => [g.team, g.has_assistant])), [map]);
  const height = TOP + Math.max(...nodes.map((n) => n.row + 1)) * ROW_H + 8;
  const width = LEFT + COLUMN_TITLES.length * COL_W;

  function toggle(group: string | null) {
    if (!group) return;
    const next = new Set(collapsed);
    if (next.has(group)) next.delete(group);
    else next.add(group);
    setCollapsed(next);
  }

  const edges = map.edges.filter((e) => byId.has(e.source) && byId.has(e.target));
  return (
    <div className="map-scroll">
      <svg width={width} height={height} className="impact-map" role="img" aria-label="影響マップ">
        {COLUMN_TITLES.map((t, i) => (
          <text key={t} x={LEFT + i * COL_W + 4} y={18} className="column-title">
            {t}
          </text>
        ))}
        {edges.map((e) => {
          const s = byId.get(e.source)!;
          const t = byId.get(e.target)!;
          const tone = edgeTone(e.source, e.target, selection);
          const sx = x(s) + NODE_W;
          const sy = y(s) + NODE_H / 2;
          const sameColumn = s.column === t.column;
          const tx = sameColumn ? x(t) + NODE_W : x(t);
          const ty = y(t) + NODE_H / 2;
          const d = sameColumn
            ? `M${sx},${sy} C${sx + 18},${sy} ${tx + 18},${ty} ${tx},${ty}`
            : `M${sx},${sy} C${sx + 12},${sy} ${tx - 12},${ty} ${tx},${ty}`;
          return <path key={`${e.source}->${e.target}`} d={d} className={`edge ${tone}`} />;
        })}
        {nodes.map((n) => {
          const tone = nodeTone(n.id, n.group, selection, view);
          const isDomain = n.type === "domain";
          const preparing = isDomain && n.group !== null && !assistant.get(n.group);
          const label = isDomain
            ? `${collapsed.has(n.group ?? "") ? "▸" : "▾"} ${n.label}${preparing ? "・準備中" : ""}`
            : n.type === "vehicle"
              ? n.label
              : n.id;
          return (
            <g
              key={n.id}
              transform={`translate(${x(n)},${y(n)})`}
              className={`node ${tone} ${n.type}`}
              onClick={() => isDomain && toggle(n.group)}
            >
              <title>{n.type === "domain" || n.type === "vehicle" ? n.label : `${n.id}: ${n.label}`}</title>
              <rect width={NODE_W} height={NODE_H} rx={5} />
              <text x={8} y={15}>
                {label}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="legend">
        <span className="swatch origin" />
        変更の起点
        <span className="swatch impacted" />
        影響を受ける
        <span className="swatch cross" />
        領域をまたぐ影響
        <span className="muted">（領域を押すと折りたためます。「準備中」はアシスタントがまだいない領域）</span>
      </div>
    </div>
  );
}
