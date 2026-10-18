import { describe, it, expect } from "vitest";
import type { Evidence } from "../types";
import { simulationStages, firstNodeStage } from "./execution";

describe("v2 simulator stages", () => {
  it("keeps runtime order, repeated symbols, fused and split origins and eliminated views distinct", () => {
    const data = {
      graph: {
        nodes: [
          { id: "a", index: 0, group: "CONV_2D", unitIds: ["shared"] },
          { id: "b", index: 1, group: "ADD", unitIds: ["shared", "split"] },
          {
            id: "view",
            index: 2,
            group: "RESHAPE",
            unitIds: [],
            disposition: "eliminated",
          },
        ],
      },
      executionPlan: {
        units: [
          {
            id: "shared",
            nodes: ["a", "b"],
            symbol: "same_function",
            eventIds: ["e0", "e2"],
          },
          {
            id: "split",
            nodes: ["b"],
            symbol: "same_function",
            eventIds: ["e1"],
          },
        ],
      },
      events: [
        { id: "root", scope: "inference" },
        ...["e0", "e1", "e2"].map((id) => ({
          id,
          scope: "execution-unit",
          entry: "128",
        })),
      ],
    } as unknown as Evidence;
    const stages = simulationStages(data);
    expect(stages.map((s) => s.unitId)).toEqual(["shared", "split", "shared"]);
    expect(stages.map((s) => s.index)).toEqual([0, 1, 2]);
    expect(stages[0].nodes).toEqual(["a", "b"]);
    expect(stages[1].label).toContain("Node 1");
    expect(stages[1].label).toContain("split");
    expect(firstNodeStage(stages, "b")).toBe(0);
    expect(firstNodeStage(stages, "view")).toBeNull();
  });
});
