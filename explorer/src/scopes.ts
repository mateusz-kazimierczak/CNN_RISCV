import type { Evidence, Event, GraphNode } from "./types";

// A logical selection is a derived view, never an extra runtime event. A fused
// unit is counted once and its full cost remains shared by all its origins.
export function nodeScope(data: Evidence, node: GraphNode): Event {
  const units = data.executionPlan.units.filter((u) =>
    node.unitIds.includes(u.id),
  );
  const eventIds = new Set(units.flatMap((u) => u.eventIds));
  const events = data.events.filter((e) => eventIds.has(e.id));
  if (units.length === 1 && units[0].nodes.length === 1 && events.length === 1)
    return events[0];
  const counts: Record<string, string> = {};
  const mix: Record<string, string> = {};
  for (const e of events) {
    for (const [pc, n] of Object.entries(e.counts))
      counts[pc] = (BigInt(counts[pc] || 0) + BigInt(n)).toString();
    for (const [key, n] of Object.entries(e.mix))
      mix[key] = (BigInt(mix[key] || 0) + BigInt(n)).toString();
  }
  const available =
    units.length > 0 && units.every((u) => u.eventIds.length > 0);
  return {
    id: `logical:${node.id}`,
    name: `Node ${node.index} · ${node.type}`,
    kind: "logical",
    scope: "logical-view",
    nodeId: node.id,
    unitId: null,
    evidence: available ? "derived" : "unavailable",
    shared: units.some((u) => u.nodes.length > 1),
    total: events.reduce((n, e) => n + BigInt(e.total), 0n).toString(),
    counts,
    mix,
  };
}

export function selectionScopes(data: Evidence): Event[] {
  const scopes: Event[] = data.events.map((e) => ({
    ...e,
    shared: data.executionPlan.units.some(
      (u) => u.id === e.unitId && u.nodes.length > 1,
    ),
  }));
  for (const n of data.graph.nodes) {
    const scope = nodeScope(data, n);
    if (!scopes.some((e) => e.id === scope.id)) scopes.push(scope);
  }
  return scopes;
}
