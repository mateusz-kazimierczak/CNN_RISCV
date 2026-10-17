import { describe, it, expect } from "vitest";
import {
  initialSession,
  sessionMessage,
  registerValue,
  type SimulationSnapshot,
} from "./types";
const snapshot: SimulationSnapshot = {
  pc: "2147507372",
  retired: "4867278370",
  serializationRetries: "1",
  registers: Array(32).fill("18446744073709551615"),
  region: "invoke",
  node: 4,
  entered: 4,
  inferenceComplete: false,
  reason: "breakpoint",
  instruction: null,
};
describe("live simulation state", () => {
  it("discards late snapshots, progress and output from a previous process", () => {
    const state = { ...initialSession, generation: 3 };
    for (const message of [
      { type: "stopped", snapshot },
      { type: "progress", retired: "999" },
      { type: "output", text: "old" },
      { type: "disassembly", instructions: [] },
    ])
      expect(sessionMessage(state, { ...message, generation: 2 })).toBe(state);
  });
  it("clears live state and register comparisons on replay but retains breakpoints", () => {
    const breakpoints = [{ key: 1, pc: snapshot.pc, node: 4 }];
    const state = sessionMessage(
      {
        ...initialSession,
        generation: 1,
        snapshot,
        previous: snapshot,
        breakpoints,
        disassembly: [
          { pc: "4096", bits: "663", length: 4, text: "auipc t0,0x0" },
        ],
      },
      { type: "reset", generation: 2, replaying: true, target: 3 },
    );
    expect(state.snapshot).toBeNull();
    expect(state.previous).toBeNull();
    expect(state.disassembly).toEqual([]);
    expect(state.breakpoints).toEqual(breakpoints);
    expect(state.target).toBe(3);
    expect(state.replaying).toBe(true);
  });
  it("keeps exact register values and retirement counts beyond 32 bits", () => {
    expect(registerValue("18446744073709551615", "hex")).toBe(
      "0xffffffffffffffff",
    );
    expect(registerValue("18446744073709551615", "signed")).toBe("-1");
    expect(registerValue("18446744073709551615", "unsigned")).toBe(
      "18446744073709551615",
    );
    const state = sessionMessage(
      { ...initialSession, generation: 1 },
      { type: "stopped", generation: 1, snapshot, target: null },
    );
    expect(state.retired).toBe("4867278370");
    expect(state.snapshot?.pc).toBe(snapshot.pc);
  });
  it("compares consecutive stopped snapshots without interpreting progress as a stop", () => {
    let state = sessionMessage(
      { ...initialSession, generation: 1 },
      { type: "stopped", generation: 1, snapshot },
    );
    state = sessionMessage(state, {
      type: "running",
      generation: 1,
      target: 7,
    });
    state = sessionMessage(state, {
      type: "progress",
      generation: 1,
      retired: "4867279999",
      entered: 5,
    });
    expect(state.snapshot).toBe(snapshot);
    expect(state.status).toBe("running");
    state = sessionMessage(state, {
      type: "stopped",
      generation: 1,
      snapshot: { ...snapshot, pc: "2147507348", reason: "step" },
    });
    expect(state.previous).toBe(snapshot);
    expect(state.status).toBe("paused");
  });
});
