export type Counts = Record<string, string>;
export interface Frame {
  function: string;
  file: string | null;
  line: number | null;
  discriminator: number;
}
export interface Instruction {
  pc: string;
  bits: string;
  length: number;
  mnemonic: string;
  operands: string;
  category: string;
  functionId: string | null;
  functionIds: string[];
  frames: Frame[];
  transfer: { kind: string; target: string | null };
}
export interface Block {
  id: string;
  start: string;
  pcs: string[];
  successors: { to: string; kind: string }[];
  calls: { pc: string; target: string | null; kind: string }[];
}
export interface Loop {
  id: string;
  kind: string;
  header: string | null;
  blocks: string[];
  latches: string[];
  children: string[];
  parent: string | null;
  pcs: string[];
  exclusivePcs: string[];
  confidence: string;
}
export interface Func {
  id: string;
  name: string;
  aliases: string[];
  linkageNames: string[];
  address: string;
  size: number;
  pcs: string[];
  cfg: {
    blocks: Block[];
    loops: Loop[];
    complete: boolean;
    unresolved: { pc: string; reason: string }[];
  };
}
export interface Event {
  id: string;
  name: string;
  kind: string;
  nodeId: string | null;
  scope:
    | "inference"
    | "setup"
    | "execution-unit"
    | "invocation-overhead"
    | "logical-view";
  evidence: "measured" | "derived" | "unavailable";
  unitId: string | null;
  shared?: boolean;
  total: string;
  counts: Counts;
  mix: Counts;
  entry?: string;
  returnPc?: string;
  complete?: boolean;
  status?: string;
}
export interface GraphNode {
  id: string;
  index: number;
  type: string;
  group: string;
  inputs: number[];
  outputs: number[];
  unitIds: string[];
  disposition: "executed" | "eliminated";
  reason?: string;
  input_shapes: number[][];
  output_shapes: number[][];
  logical_macs: string;
  executed_products: string | null;
  options: Record<string, number | boolean | string>;
  convolution?: {
    kernel: number[];
    stride: number[];
    dilation: number[];
    padding: string;
  };
}
export interface Tensor {
  id: number;
  name: string;
  shape: number[];
  type: string;
  constant: boolean;
  quantization: null | { scales: number[]; zeroPoints: string[]; axis: number };
  producer: string | null;
  consumers: string[];
}
export interface Source {
  id: string;
  path: string;
  archivePath: string | null;
  sha256: string | null;
  status: string;
}
export interface ArtifactFunction {
  name: string;
  linkageName: string;
  startLine: number;
  endLine: number;
}
export interface Artifact {
  stage: string;
  path: string;
  archivePath: string;
  sha256: string;
  functions: ArtifactFunction[];
}
export interface CompilerUnit {
  id: string;
  source: string;
  directory: string;
  arguments: string[];
  baseArguments: string[];
  dependencyHashes: Record<string, string>;
  artifacts: Artifact[];
}
export interface Annotation {
  id: string;
  title: string;
  category: string;
  description: string;
  pcs: string[];
  elfHash: string;
  sourceHashes: Record<string, string>;
  evidence: string;
  status: string;
}
export interface Evidence {
  executionPlan: {
    units: ExecutionUnit[];
    artifacts?: { name: string; archivePath: string; sha256: string }[];
  };
  memoryPlan: MemoryPlan | null;
  measurementSummary?: {
    inference: Record<string, Metric>;
    footprint: Record<string, Metric>;
  } | null;
  preparedParameters: {
    nodes: {
      node: number;
      integers: Record<string, number | number[]>;
      [key: string]: unknown;
    }[];
    [key: string]: unknown;
  } | null;
  registers?: RegisterEvidence;
  schemaVersion: number;
  provenance: {
    configuration: string;
    compiler: string;
    input_seed: number;
    output_fnv1a: string;
    hashes: Record<string, string>;
    sourceSnapshotStatus: string;
    boundaries: string;
    [key: string]: unknown;
  };
  graph: {
    nodes: GraphNode[];
    tensors: Tensor[];
    edges: { id: string; source: string; target: string; tensorId: number }[];
    inputs: number[];
    outputs: number[];
  };
  events: Event[];
  instructions: Record<string, Instruction>;
  functions: Func[];
  sources: Record<string, Source>;
  annotations: Annotation[];
  compilerUnits: CompilerUnit[];
  compilerEvidence?: {
    loadableIdentical: boolean;
    measuredElfHash: string;
    analysisElfHash: string;
    commandInventoryPath: string;
  } | null;
  totals: { inference: string; allocation: string | null; overhead: string };
  capabilities: {
    compiler: boolean;
    loops: boolean;
    sourceMappedInstructions: number;
    staticInstructions: number;
  };
}
export interface ExecutionUnit {
  id: string;
  order: number;
  nodes: string[];
  eventIds: string[];
  symbol: string;
  implementation: string;
  arithmetic_backend: string;
  inputs: number[];
  outputs: number[];
  source: { file: string; line: number; end_line: number } | null;
  memory: Record<string, unknown> | null;
  work: {
    logical_macs: string | null;
    executed_products: string | null;
    evidence: string;
    policy?: string;
  };
  notes: string[];
}
export interface Metric {
  value: string | { numerator: string; denominator: string } | null;
  unit: string;
  scope: string;
  evidence: "measured" | "derived" | "unavailable";
  policy?: string;
}
export interface MemoryPlan {
  arena_bytes: number;
  arena_alignment: number;
  rodata_bytes: number;
  algorithm: string;
  requests: {
    name: string;
    size_bytes: number;
    alignment: number;
    start: number;
    end: number;
    category: string;
  }[];
  placements: { name: string; offset: number | null }[];
  tensors: { tensor: number; offset: number | null; [key: string]: unknown }[];
  aliases: {
    node: number;
    source: number;
    output: number;
    enabled: boolean;
    reason: string;
  }[];
  scratch: unknown[];
  summary: {
    peak_live_activation_bytes: number;
    peak_live_scratch_bytes: number;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}
export const count = (counts: Counts, pc: string) => BigInt(counts[pc] || "0");
export const sum = (pcs: string[], counts: Counts) =>
  pcs.reduce((s, pc) => s + count(counts, pc), 0n);
export const exact = (n: string | bigint) => BigInt(n).toLocaleString("en-US");
export const compact = (n: string | bigint) => {
  const v = BigInt(n);
  for (const [u, s, digits] of [
    [1000000000n, "B", 3],
    [1000000n, "M", 2],
    [1000n, "K", 2],
  ] as const)
    if (v >= u) {
      const precision = 10n ** BigInt(digits),
        rounded = (v * precision + u / 2n) / u;
      return `${rounded / precision}.${(rounded % precision).toString().padStart(digits, "0")}${s}`;
    }
  return v.toString();
};
export const percent = (n: bigint, d: bigint) =>
  d ? `${Number((n * 10000n + d / 2n) / d) / 100}%` : "0%";
export const hex = (pc: string) => "0x" + BigInt(pc).toString(16);

export interface RegisterVariable {
  id: string;
  name: string;
  type: string;
  function: string;
  kind: "local" | "parameter";
  declaration: { file: string; line: number } | null;
}
export interface RegisterLocation {
  variableId: string;
  low: string;
  high: string;
  kind: "value" | "address" | "piece";
  description: string;
  expression: string;
}
export interface RegisterEvidence {
  schemaVersion: 1;
  elfHash: string;
  semantics: "before-instruction";
  variables: Record<string, RegisterVariable>;
  locations: Record<string, RegisterLocation[]>;
  relations?: Record<string, RegisterRelation[]>;
  roles?: RegisterRole[];
  compilerOrigins?: Record<string, Record<string, CompilerRegisterOrigin[]>>;
  coverage: {
    compilationUnits: number;
    supportedLocations: number;
    unsupportedExpressions: number;
    skippedScopes: number;
    symbolicRelations?: number;
  };
}
export interface RegisterRelation {
  variableId: string;
  low: string;
  high: string;
  offset: string;
  bytes: number;
  signed: boolean;
  expression: string;
}
export interface RegisterRole {
  functionId: string;
  loopId: string;
  register: string;
  kind: "pointer" | "boundary";
  pcs: string[];
  stride: number;
  loadPcs: string[];
  updatePcs: string[];
  comparePc: string;
  sourceVariableIds: string[];
  relatedRegister?: string;
  span?: {
    definitionPc: string;
    register: string;
    source?: { name: string; file: string; line: number; sha256: string };
  };
}
export interface CompilerRegisterOrigin {
  name: string;
  unitId: string;
  artifactPath: string;
  startLine: number;
  endLine: number;
  assemblyPath: string;
  assemblyLine: number;
  matching: "unique-loop-window";
  loopId: string;
}
