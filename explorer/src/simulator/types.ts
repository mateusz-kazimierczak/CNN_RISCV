export type SimulationStopReason =
  | "ready"
  | "snapshot"
  | "step"
  | "breakpoint"
  | "stage-breakpoint"
  | "inference-entry"
  | "inference-complete"
  | "trap"
  | "wait"
  | "attribution-error"
  | "exited";
export interface SimulationSnapshot {
  pc: string;
  retired: string;
  serializationRetries: string;
  registers: string[];
  region: string;
  node: number;
  entered: number;
  inferenceComplete: boolean;
  reason: SimulationStopReason;
  error?: string;
  instruction: { bits: string; length: number; text: string } | null;
  trap?: { pc: string; cause: string; name: string };
}
export interface SimulationBreakpoint {
  key: number;
  pc: string;
  node: number;
}
export interface SimulationSession {
  generation: number;
  status: "disconnected" | "ready" | "running" | "paused" | "exited";
  snapshot: SimulationSnapshot | null;
  previous: SimulationSnapshot | null;
  breakpoints: SimulationBreakpoint[];
  target: number | null;
  replaying: boolean;
  retired: string;
  entered: number;
  output: string;
  error: string;
  result?: {
    passed: boolean;
    checksum: string | null;
    expected: string;
    exitCode: number;
  };
  memory?: { address: string; hex: string };
}
export const initialSession: SimulationSession = {
  generation: 0,
  status: "disconnected",
  snapshot: null,
  previous: null,
  breakpoints: [],
  target: null,
  replaying: false,
  retired: "0",
  entered: -1,
  output: "",
  error: "",
};
export function sessionMessage(
  state: SimulationSession,
  message: any,
): SimulationSession {
  if (
    typeof message.generation === "number" &&
    message.generation < state.generation
  )
    return state;
  if (message.type === "reset")
    return {
      ...initialSession,
      status: "running",
      generation: message.generation,
      breakpoints: state.breakpoints,
      target: message.target,
      replaying: message.replaying,
    };
  if (
    message.generation !== undefined &&
    message.generation !== state.generation
  )
    return state;
  switch (message.type) {
    case "connected":
      return { ...state, status: "ready" };
    case "running":
      return { ...state, status: "running", target: message.target, error: "" };
    case "stopped":
      return {
        ...state,
        status: message.snapshot.reason === "exited" ? "exited" : "paused",
        previous: state.snapshot,
        snapshot: message.snapshot,
        retired: message.snapshot.retired,
        entered: message.snapshot.entered,
        target: message.target,
        replaying: false,
        error: message.snapshot.error || "",
      };
    case "progress":
      return { ...state, retired: message.retired, entered: message.entered };
    case "breakpoints":
      return { ...state, breakpoints: message.breakpoints, error: "" };
    case "memory":
      return {
        ...state,
        memory: { address: message.address, hex: message.hex },
        error: "",
      };
    case "output":
      return { ...state, output: (state.output + message.text).slice(-262144) };
    case "result":
      return { ...state, result: message };
    case "native-closed":
      return state.status === "exited"
        ? state
        : {
            ...state,
            status: "ready",
            snapshot: null,
            previous: null,
            error: "Simulator process ended. Press Start to restart.",
          };
    case "error":
      return {
        ...state,
        error: message.error,
        status: message.running
          ? "running"
          : state.snapshot
            ? state.status === "running"
              ? "paused"
              : state.status
            : "ready",
      };
    default:
      return state;
  }
}
export const ABI = [
  "zero",
  "ra",
  "sp",
  "gp",
  "tp",
  "t0",
  "t1",
  "t2",
  "s0/fp",
  "s1",
  "a0",
  "a1",
  "a2",
  "a3",
  "a4",
  "a5",
  "a6",
  "a7",
  "s2",
  "s3",
  "s4",
  "s5",
  "s6",
  "s7",
  "s8",
  "s9",
  "s10",
  "s11",
  "t3",
  "t4",
  "t5",
  "t6",
];
export function registerValue(value: string, format: string) {
  const n = BigInt(value);
  return format === "signed"
    ? BigInt.asIntN(64, n).toString()
    : format === "unsigned"
      ? n.toString()
      : "0x" + n.toString(16).padStart(16, "0");
}
