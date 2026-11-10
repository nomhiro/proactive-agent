import { describe, expect, test } from "vitest";
import { compactRows, edgeTone, nodeTone, selectionFrom, visibleNodes } from "./mapView";
import type { MapNode, NotificationDoc } from "./types";

const TEAM = { team: "integrated_control", chief: false };
const CHIEF = { team: "chief_engineer", chief: true };

const notification: NotificationDoc = {
  id: "n-1",
  team: "integrated_control",
  origin_artifact_id: "SIG-BrkPedalPos",
  impacted_ids: ["MDL-MotorTq"],
  highlight_ids: ["SPEC-BRK-04", "SIG-BrkPedalPos", "MDL-MotorTq"],
  cross_team_edges: [["SIG-BrkPedalPos", "MDL-MotorTq"]],
  classification: "notify_now",
  reason: "",
  created_at: "2026-11-17T21:30:00+09:00",
  delivered_at: "2026-11-18T08:00:00+09:00",
};
const sel = selectionFrom(notification);

describe("nodeTone", () => {
  test("origin is filled, impacted is red, other highlight is context, rest is dim", () => {
    expect(nodeTone("SIG-BrkPedalPos", "integrated_control", sel, TEAM)).toBe("origin");
    expect(nodeTone("MDL-MotorTq", "motor_control", sel, TEAM)).toBe("impacted");
    expect(nodeTone("SPEC-BRK-04", "integrated_control", sel, TEAM)).toBe("context");
    expect(nodeTone("REQ-301", "battery_control", sel, TEAM)).toBe("dim");
  });

  test("without selection, team view emphasizes own domain and chief view is even", () => {
    expect(nodeTone("REQ-112", "integrated_control", null, TEAM)).toBe("own");
    expect(nodeTone("REQ-201", "motor_control", null, TEAM)).toBe("other");
    expect(nodeTone("REQ-201", "motor_control", null, CHIEF)).toBe("even");
    expect(nodeTone("VEHICLE", null, null, TEAM)).toBe("own");
  });
});

describe("edgeTone", () => {
  test("cross-team edges in the selection are dashed red", () => {
    expect(edgeTone("SIG-BrkPedalPos", "MDL-MotorTq", sel)).toBe("cross");
    expect(edgeTone("SPEC-BRK-04", "SIG-BrkPedalPos", sel)).toBe("normal");
    expect(edgeTone("REQ-301", "SPEC-BAT-02", sel)).toBe("dim");
    expect(edgeTone("REQ-301", "SPEC-BAT-02", null)).toBe("normal");
  });
});

describe("visibleNodes", () => {
  const nodes: MapNode[] = [
    { id: "VEHICLE", label: "架空SUV", type: "vehicle", column: 0, row: 0, group: null },
    { id: "DOMAIN-battery_control", label: "電池制御", type: "domain", column: 1, row: 0, group: "battery_control" },
    { id: "REQ-301", label: "r", type: "requirement", column: 2, row: 0, group: "battery_control" },
    { id: "REQ-112", label: "r", type: "requirement", column: 2, row: 1, group: "integrated_control" },
  ];

  test("collapsed domain hides its nodes but keeps the domain node", () => {
    const shown = visibleNodes(nodes, new Set(["battery_control"])).map((n) => n.id);
    expect(shown).toEqual(["VEHICLE", "DOMAIN-battery_control", "REQ-112"]);
  });

  test("rows are compacted per column after collapsing", () => {
    const rows = compactRows(visibleNodes(nodes, new Set(["battery_control"])));
    expect(rows.find((n) => n.id === "REQ-112")?.row).toBe(0);
  });
});
