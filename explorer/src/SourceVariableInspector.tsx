import type { Evidence } from "./types";
import { InspectorPopover, type InspectorAnchor } from "./InspectorPopover";
import { explainSourceVariable } from "./sourceVariables";

export interface SourceVariableSelection extends InspectorAnchor {
  name: string;
  file: string;
  line: number;
}
export function SourceVariableInspector({
  data,
  selection,
  nodeId,
  onClose,
  live = false,
}: {
  data: Evidence;
  selection: SourceVariableSelection;
  nodeId: string | null;
  onClose: () => void;
  live?: boolean;
}) {
  const help = explainSourceVariable(data, { ...selection, nodeId });
  const node = data.graph.nodes.find((node) => node.id === nodeId);
  const labels = {
    fixed: "Model-derived value",
    loop: "Loop variable",
    varying: "Changes during execution",
    unavailable: "Value unavailable",
  };
  return (
    <InspectorPopover
      selection={selection}
      label={`Source variable ${selection.name}`}
      name={selection.name}
      context={`${selection.file.split("/").pop()}:${selection.line}`}
      eyebrow="C++ VARIABLE"
      onClose={onClose}
      footer={
        <>
          {node
            ? `Node ${node.index} · ${node.group}`
            : "No single operator selected"}{" "}
          ·{" "}
          {live
            ? "Model/source evidence; this is not a live C++ variable evaluation."
            : "Runtime variable values were not recorded."}
        </>
      }
    >
      <div className="register-variable source-variable">
        <span className="chip">{labels[help.kind]}</span>
        {help.value !== undefined && (
          <code className="source-variable-value">
            {selection.name} = {help.value}
          </code>
        )}
        <p>{help.description}</p>
        {help.range && (
          <code className="source-variable-value">{help.range}</code>
        )}
        {help.expression && (
          <code className="source-variable-expression">{help.expression}</code>
        )}
        {help.evidence.length > 0 && (
          <details>
            <summary>Source and model evidence</summary>
            {help.evidence.map((evidence, index) => (
              <small key={index}>{evidence}</small>
            ))}
            <small>
              Variable bindings are checked against reviewed source hashes.
            </small>
          </details>
        )}
      </div>
    </InspectorPopover>
  );
}
