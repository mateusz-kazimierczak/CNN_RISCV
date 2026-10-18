import type { Evidence } from "../types";

export interface SimulationStage {
  index: number;
  unitId: string;
  eventId: string;
  nodes: string[];
  entry: string;
  label: string;
}

// Observations define live order; graph indices are not execution positions.
export function simulationStages(data: Evidence): SimulationStage[] {
  const events = new Map(
    data.executionPlan.units.flatMap((u) =>
      u.eventIds.map((id) => [id, u] as const),
    ),
  );
  return data.events
    .filter((e) => e.scope === "execution-unit")
    .map((e, index) => {
      const u = events.get(e.id)!;
      const node =
        u.nodes.length === 1
          ? data.graph.nodes.find((n) => n.id === u.nodes[0])
          : null;
      const label = node
        ? `Node ${node.index} · ${node.group.replaceAll("_", " ")}${node.unitIds.length > 1 ? ` · ${u.id}` : ""}`
        : `Unit ${u.id} · nodes ${u.nodes.join(", ")}`;
      return {
        index,
        unitId: u.id,
        eventId: e.id,
        nodes: u.nodes,
        entry: e.entry!,
        label,
      };
    });
}
export function firstNodeStage(
  stages: SimulationStage[],
  nodeId: string,
): number | null {
  return stages.find((s) => s.nodes.includes(nodeId))?.index ?? null;
}
