import { memo, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  Handle,
  Position,
  useReactFlow,
  type NodeProps,
  type Node,
} from "@xyflow/react";
import ELK from "elkjs/lib/elk.bundled.js";
import "@xyflow/react/dist/style.css";
import type { Evidence } from "./types";
import { compact, percent } from "./types";
type Data = {
  title: string;
  index: number;
  shape: string;
  total: string;
  share: string;
  heat: number;
  [key: string]: unknown;
};
const Operator = memo(({ data, selected }: NodeProps<Node<Data>>) => (
  <div
    className={`graph-operator ${selected ? "active" : ""}`}
    style={{
      borderLeftColor: `hsl(${35 + 150 * (1 - data.heat)}, ${35 + data.heat * 40}%, ${38 + data.heat * 20}%)`,
    }}
  >
    <Handle type="target" position={Position.Top} />
    <div className="graph-node-top">
      <span className="node-index">{String(data.index).padStart(2, "0")}</span>
      <strong>{data.title}</strong>
    </div>
    <div className="graph-shape">{data.shape}</div>
    <div className="graph-node-metric">
      <span>
        {compact(data.total)} <small>instr</small>
      </span>
      <span>{data.share}</span>
    </div>
    <Handle type="source" position={Position.Bottom} />
  </div>
));
const nodeTypes = { operator: Operator };
function Graph({
  data,
  selected,
  onSelect,
}: {
  data: Evidence;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [nodes, setNodes] = useState<Node<Data>[]>([]),
    [error, setError] = useState("");
  const flow = useReactFlow();
  const edges = useMemo(
    () =>
      data.graph.edges.map((e) => ({
        ...e,
        style: { stroke: "#526773", strokeWidth: 1.4 },
        animated: false,
      })),
    [data],
  );
  useEffect(() => {
    let cancelled = false;
    const elk = new ELK();
    elk
      .layout({
        id: "model",
        layoutOptions: {
          "elk.algorithm": "layered",
          "elk.direction": "DOWN",
          "elk.spacing.nodeNode": "35",
          "elk.layered.spacing.nodeNodeBetweenLayers": "30",
        },
        children: data.graph.nodes.map((n) => ({
          id: n.id,
          width: 185,
          height: 83,
        })),
        edges: data.graph.edges.map((e) => ({
          id: e.id,
          sources: [e.source],
          targets: [e.target],
        })),
      })
      .then((layout) => {
        if (cancelled) return;
        const eventMap = new Map(data.events.map((e) => [e.id, e]));
        const max = data.graph.nodes.reduce((m, n) => {
          const v = BigInt(eventMap.get(n.eventId)?.total || 0);
          return v > m ? v : m;
        }, 1n);
        setNodes(
          data.graph.nodes.map((n) => {
            const pos = layout.children!.find((p) => p.id === n.id)!;
            const total = eventMap.get(n.eventId)?.total || "0";
            return {
              id: n.id,
              type: "operator",
              position: { x: pos.x || 0, y: pos.y || 0 },
              data: {
                title: n.group.replaceAll("_", " "),
                index: n.index,
                shape: n.output_shapes[0]?.join(" × ") || "",
                total,
                share: percent(BigInt(total), BigInt(data.totals.inference)),
                heat: Number((BigInt(total) * 1000n) / max) / 1000,
              },
            };
          }),
        );
      })
      .catch((e) => setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [data]);
  useEffect(() => {
    if (!nodes.length) return;
    const n = nodes.find((n) => n.id === selected);
    if (n)
      void flow.setCenter(n.position.x + 92, n.position.y + 150, {
        zoom: 0.82,
        duration: 350,
      });
    else void flow.fitView({ duration: 300, padding: 0.15 });
  }, [selected, nodes, flow]);
  if (error)
    return <div className="notice">Graph layout unavailable: {error}</div>;
  return (
    <ReactFlow
      nodes={nodes.map((n) => ({ ...n, selected: n.id === selected }))}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, n) => onSelect(n.id)}
      nodesDraggable={false}
      nodesConnectable={false}
      minZoom={0.08}
      maxZoom={1.8}
      proOptions={{ hideAttribution: true }}
    >
      <Background color="#2b3d48" gap={20} size={1} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
export function ModelGraph(props: {
  data: Evidence;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <ReactFlowProvider>
      <Graph {...props} />
    </ReactFlowProvider>
  );
}
