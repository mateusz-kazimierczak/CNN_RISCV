import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { unzipSync, strFromU8 } from "fflate";
import type { Evidence } from "./types";
import reviewedSources from "../../tools/explorer/reviewed_sources.json";
import { explainSourceVariable, sourceIdentifierAt } from "./sourceVariables";
const conv =
  ".deps/tflite-micro/tensorflow/lite/kernels/internal/reference/integer_ops/conv.h";
const depthwise =
  ".deps/tflite-micro/tensorflow/lite/kernels/internal/reference/integer_ops/depthwise_conv.h";
function fixture(): Evidence {
  return {
    graph: {
      nodes: [
        {
          id: "4",
          index: 4,
          type: "CONV_2D",
          inputs: [10, 11],
          outputs: [12],
          options: {
            StrideH: 1,
            StrideW: 1,
            DilationHFactor: 1,
            DilationWFactor: 1,
          },
        },
      ],
      tensors: [
        {
          id: 10,
          type: "INT8",
          shape: [1, 112, 112, 16],
          quantization: { zeroPoints: ["-3"] },
        },
        { id: 11, type: "INT8", shape: [96, 1, 1, 16] },
        { id: 12, type: "INT8", shape: [1, 112, 112, 96] },
      ],
    },
    sources: {
      [conv]: { sha256: reviewedSources[conv] },
      [depthwise]: { sha256: reviewedSources[depthwise] },
    },
  } as unknown as Evidence;
}
const help = (
  data: Evidence,
  name: string,
  file = conv,
  nodeId: string | null = "4",
  line = 72,
) => explainSourceVariable(data, { file, name, line, nodeId });
describe("source variables scoped to a selected layer", () => {
  it("shows fixed shape values and distinguishes a changing loop index", () => {
    const data = fixture();
    expect(help(data, "batches").value).toBe("1");
    expect(help(data, "input_depth").value).toBe("16");
    expect(help(data, "output_depth").value).toBe("96");
    expect(help(data, "filter_shape").value).toBe("[96, 1, 1, 16]");
    expect(help(data, "batch")).toMatchObject({
      kind: "loop",
      range: "0 ≤ batch < 1",
    });
    expect(help(data, "batch").value).toBeUndefined();
    expect(help(data, "in_channel").range).toBe("0 ≤ in_channel < 16");
    expect(help(data, "acc").kind).toBe("varying");
    expect(help(data, "input_val").value).toBeUndefined();
  });
  it("uses each operator's tensors even when source and machine code are shared", () => {
    const data = fixture();
    data.graph.nodes.push({
      ...data.graph.nodes[0],
      id: "9",
      inputs: [13, 14],
      outputs: [15],
    });
    data.graph.tensors.push(
      { ...data.graph.tensors[0], id: 13, shape: [2, 56, 56, 144] },
      { ...data.graph.tensors[1], id: 14, shape: [24, 1, 1, 144] },
      { ...data.graph.tensors[2], id: 15, shape: [2, 56, 56, 24] },
    );
    expect(help(data, "batches", conv, "9").value).toBe("2");
    expect(help(data, "input_depth", conv, "9").value).toBe("144");
    expect(help(data, "output_depth", conv, "4").value).toBe("96");
    expect(help(data, "batches", conv, null).kind).toBe("unavailable");
  });
  it("fails closed for stale sources, other overloads, wrong operators and invalid shapes", () => {
    const data = fixture();
    expect(help(data, "batches", conv, "4", 150).kind).toBe("unavailable");
    expect(help(data, "batches", depthwise).kind).toBe("unavailable");
    data.sources[conv].sha256 = "stale";
    expect(help(data, "batches").kind).toBe("unavailable");
    data.sources[conv].sha256 = reviewedSources[conv];
    data.graph.tensors[2].shape[0] = 2;
    expect(help(data, "batches").kind).toBe("unavailable");
  });
  it("does not invent quantization values or contents without parameter provenance", () => {
    const data = fixture();
    expect(help(data, "input_offset").value).toBeUndefined();
    expect(help(data, "output_activation_max").value).toBeUndefined();
    expect(help(data, "output_multiplier").kind).toBe("unavailable");
    expect(help(data, "filter_data").value).toBeUndefined();
  });
  it("only selects identifiers outside comments/strings and excludes keywords and calls", () => {
    const text =
      'const int batches = MatchingDim(input_shape, 0); // batches\n/* batch */ for (int batch = 0; batch < batches; ++batch) {\nconst char* name = "batches";';
    const lines = text.split("\n");
    expect(sourceIdentifierAt(text, 1, lines[0].indexOf("batches") + 2)).toBe(
      "batches",
    );
    expect(
      sourceIdentifierAt(text, 1, lines[0].lastIndexOf("batches") + 2),
    ).toBeNull();
    expect(sourceIdentifierAt(text, 1, 2)).toBeNull();
    expect(
      sourceIdentifierAt(text, 1, lines[0].indexOf("MatchingDim") + 2),
    ).toBeNull();
    expect(sourceIdentifierAt(text, 2, 5)).toBeNull();
    expect(
      sourceIdentifierAt(text, 3, lines[2].indexOf("batches") + 2),
    ).toBeNull();
  });
});
const bundlePath = new URL("../../build/explorer/B0.zip", import.meta.url);
it.skipIf(!existsSync(bundlePath))(
  "real B0: convolution and depthwise shape, padding, and quantization values",
  () => {
    const files = unzipSync(new Uint8Array(readFileSync(bundlePath)), {
      filter: (file) => file.name === "evidence.json",
    });
    const data = JSON.parse(strFromU8(files["evidence.json"])) as Evidence;
    expect(help(data, "batches").value).toBe("1");
    expect(help(data, "input_depth").value).toBe("16");
    expect(help(data, "output_depth").value).toBe("96");
    expect(help(data, "groups").value).toBe("1");
    expect(help(data, "pad_width").value).toBe("0");
    expect(help(data, "depth_multiplier", depthwise, "5").value).toBe("1");
    expect(help(data, "output_height", depthwise, "5").value).toBe("56");
    expect(help(data, "stride_height", depthwise, "5").value).toBe("2");
    expect(help(data, "pad_height", depthwise, "5").value).toBe("0");
    expect(help(data, "pad_height", depthwise, "2").value).toBe("1");
    expect(help(data, "input_offset", depthwise, "5").value).toBe("128");
    expect(help(data, "output_offset", depthwise, "5").value).toBe("-128");
    expect(help(data, "m", depthwise, "5").range).toBe("0 ≤ m < 1");
  },
);
