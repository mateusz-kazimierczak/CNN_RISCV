import reviewedSources from "../../tools/explorer/reviewed_sources.json";
import type { Evidence, Tensor } from "./types";

const root = ".deps/tflite-micro/tensorflow/lite/";
const conv = root + "kernels/internal/reference/integer_ops/conv.h";
const depthwise =
  root + "kernels/internal/reference/integer_ops/depthwise_conv.h";
const parameterHashes: Record<string, string> = {
  [root + "micro/kernels/conv_common.cc"]:
    "8756a28794baf1ed67d2b88f080e5f22318e95d6bfcac10984f8fb3c96a048be",
  [root + "micro/kernels/depthwise_conv_common.cc"]:
    "4156f5c33a9be5882091f03ec0d656b73a8617fb84bcc0bbe54dc0138c15650c",
  [root + "kernels/padding.h"]:
    "9479a77bb4d03401b38201b4dcf68e18c8d99d1cc961444a6ee3f758fd2757fc",
};
export interface SourceVariableHelp {
  kind: "fixed" | "loop" | "varying" | "unavailable";
  description: string;
  value?: string;
  expression?: string;
  range?: string;
  evidence: string[];
}
export interface SourceVariableContext {
  file: string;
  line: number;
  name: string;
  nodeId?: string | null;
}
const unavailable = (description: string): SourceVariableHelp => ({
  kind: "unavailable",
  description,
  evidence: [],
});
const keywords = new Set(
  "auto bool break case char class const constexpr continue default delete do double else enum explicit false float for if inline int int8_t int16_t int32_t int64_t long namespace new nullptr private public return short signed sizeof static static_cast struct switch template true typename uint8_t uint16_t uint32_t uint64_t unsigned using virtual void volatile while".split(
    " ",
  ),
);
// Preserve offsets while excluding comments and string/character literals.
export function cppCodeOnly(text: string): string {
  return text.replace(
    /\/\*[\s\S]*?\*\/|\/\/[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g,
    (match) => match.replace(/[^\n]/g, " "),
  );
}
export function sourceIdentifierAt(
  text: string,
  line: number,
  column: number,
): string | null {
  const code = cppCodeOnly(text).split("\n")[line - 1] || "";
  const index = column - 1;
  for (const match of code.matchAll(/\b[A-Za-z_]\w*\b/g)) {
    if (match.index! <= index && index < match.index! + match[0].length) {
      const name = match[0];
      if (
        keywords.has(name) ||
        /^\s*\(/.test(code.slice(match.index! + name.length))
      )
        return null;
      return name;
    }
  }
  return null;
}

/** Reviewed bindings for the int8 reference kernels, guarded by source hashes
 * and overload ranges. Values come from one selected model operator, never PC
 * frequencies. Unknown source revisions, overloads and operator scopes fail closed.
 */
export function explainSourceVariable(
  data: Evidence,
  context: SourceVariableContext,
): SourceVariableHelp {
  const { file, line, name } = context;
  const expectedHash = (reviewedSources as Record<string, string>)[file];
  const isDepthwise = file === depthwise;
  if (
    (file !== conv && !isDepthwise) ||
    !expectedHash ||
    data.sources[file]?.sha256 !== expectedHash
  )
    return unavailable(
      "No reviewed variable binding is available for this source revision.",
    );
  if (line < (isDepthwise ? 24 : 26) || line > (isDepthwise ? 122 : 136))
    return unavailable(
      "This source location is outside the supported int8 kernel overload.",
    );
  const node = data.graph.nodes.find((node) => node.id === context.nodeId);
  if (!node)
    return unavailable(
      "Select one model operator to inspect its layer-specific values. Whole-inference counts combine multiple layers.",
    );
  if (node.type !== (isDepthwise ? "DEPTHWISE_CONV_2D" : "CONV_2D"))
    return unavailable(
      "The selected operator does not use this kernel binding.",
    );
  const tensor = (id: number): Tensor | undefined =>
    data.graph.tensors.find((t) => t.id === id);
  const input = tensor(node.inputs[0]),
    filter = tensor(node.inputs[1]),
    output = tensor(node.outputs[0]);
  if (
    !input ||
    !filter ||
    !output ||
    input.type !== "INT8" ||
    filter.type !== "INT8" ||
    output.type !== "INT8"
  )
    return unavailable(
      "This binding requires recorded int8 input, filter, and output tensors.",
    );
  const validShape = (t: Tensor) =>
    t.shape.length === 4 &&
    t.shape.every((n) => Number.isSafeInteger(n) && n > 0);
  if (
    ![input, filter, output].every(validShape) ||
    input.shape[0] !== output.shape[0]
  )
    return unavailable(
      "Recorded tensor shapes do not satisfy this kernel's dimension checks.",
    );
  if (
    output.shape[3] !== filter.shape[isDepthwise ? 3 : 0] ||
    (isDepthwise && filter.shape[0] !== 1)
  )
    return unavailable(
      "Recorded filter and output depths disagree for this kernel.",
    );
  const fixed = new Map<string, SourceVariableHelp>();
  function scalar(
    name: string,
    value: number | bigint,
    expression: string,
    evidence: string[],
  ) {
    if (typeof value === "number" && !Number.isSafeInteger(value)) return;
    fixed.set(name, {
      kind: "fixed",
      value: String(value),
      expression,
      evidence,
      description:
        "Fixed for this operator, derived from its model metadata and the reviewed kernel.",
    });
  }
  function dimension(
    name: string,
    t: Tensor,
    axis: number,
    expression: string,
  ) {
    scalar(name, t.shape[axis], expression, [
      `Tensor ${t.id}: shape [${t.shape.join(", ")}]`,
      `${file}:${isDepthwise ? "51–65" : "52–71"}`,
    ]);
  }
  dimension(
    "batches",
    input,
    0,
    "MatchingDim(input_shape, 0, output_shape, 0)",
  );
  for (const [prefix, t] of [
    ["input", input],
    ["output", output],
  ] as const) {
    dimension(`${prefix}_height`, t, 1, `${prefix}_shape.Dims(1)`);
    dimension(`${prefix}_width`, t, 2, `${prefix}_shape.Dims(2)`);
    dimension(`${prefix}_depth`, t, 3, `${prefix}_shape.Dims(3)`);
    fixed.set(`${prefix}_shape`, {
      kind: "fixed",
      value: `[${t.shape.join(", ")}]`,
      description:
        "Tensor shape in NHWC order: batch, height, width, channels.",
      evidence: [`Tensor ${t.id}: ${t.name}`],
    });
  }
  dimension("filter_height", filter, 1, "filter_shape.Dims(1)");
  dimension("filter_width", filter, 2, "filter_shape.Dims(2)");
  fixed.set("filter_shape", {
    kind: "fixed",
    value: `[${filter.shape.join(", ")}]`,
    description: isDepthwise
      ? "Depthwise filter shape: 1, height, width, output channels."
      : "Convolution filter shape: output channels, height, width, input channels per group.",
    evidence: [`Tensor ${filter.id}: ${filter.name}`],
  });
  if (!isDepthwise) {
    dimension("filter_input_depth", filter, 3, "filter_shape.Dims(3)");
    const groups = input.shape[3] / filter.shape[3];
    if (
      Number.isSafeInteger(groups) &&
      groups > 0 &&
      output.shape[3] % groups === 0
    ) {
      scalar("groups", groups, "input_depth / filter_input_depth", [
        `${input.shape[3]} / ${filter.shape[3]}`,
      ]);
      scalar(
        "filters_per_group",
        output.shape[3] / groups,
        "output_depth / groups",
        [`${output.shape[3]} / ${groups}`],
      );
    }
  }
  const option = (name: string, key: string) => {
    const value = node.options[key];
    if (typeof value === "number" && Number.isSafeInteger(value) && value > 0)
      scalar(name, value, `params.${name}`, [
        `Node ${node.index}: ${key} = ${value}`,
      ]);
  };
  option("stride_width", "StrideW");
  option("stride_height", "StrideH");
  option("dilation_width_factor", "DilationWFactor");
  option("dilation_height_factor", "DilationHFactor");
  if (
    isDepthwise &&
    node.options.DepthMultiplier === output.shape[3] / input.shape[3]
  )
    option("depth_multiplier", "DepthMultiplier");
  const paramsFile =
    root +
    `micro/kernels/${isDepthwise ? "depthwise_conv_common" : "conv_common"}.cc`;
  if (data.sources[paramsFile]?.sha256 === parameterHashes[paramsFile]) {
    const zeroPoint = (t: Tensor) => {
      const points = t.quantization?.zeroPoints;
      if (!points || points.length !== 1 || !/^-?\d+$/.test(points[0]))
        return null;
      const value = BigInt(points[0]);
      return value >= -128n && value <= 127n ? value : null;
    };
    const inputZero = zeroPoint(input),
      outputZero = zeroPoint(output);
    if (inputZero !== null)
      scalar("input_offset", -inputZero, "-input_zero_point", [
        `Tensor ${input.id}: zero point ${inputZero}`,
        paramsFile,
      ]);
    if (outputZero !== null)
      scalar("output_offset", outputZero, "output_zero_point", [
        `Tensor ${output.id}: zero point ${outputZero}`,
        paramsFile,
      ]);
  }
  const paddingFile = root + "kernels/padding.h";
  if (
    data.sources[paddingFile]?.sha256 === parameterHashes[paddingFile] &&
    data.sources[paramsFile]?.sha256 === parameterHashes[paramsFile]
  ) {
    for (const [axis, suffix] of [
      [1, "height"],
      [2, "width"],
    ] as const) {
      const stride = Number(fixed.get(`stride_${suffix}`)?.value);
      const dilation = Number(fixed.get(`dilation_${suffix}_factor`)?.value);
      const effective = (filter.shape[axis] - 1) * dilation + 1;
      const same = node.options.Padding === 0,
        valid = node.options.Padding === 1;
      const expectedOutput = same
        ? Math.ceil(input.shape[axis] / stride)
        : Math.max(0, Math.floor((input.shape[axis] - effective) / stride) + 1);
      if (
        (same || valid) &&
        stride > 0 &&
        dilation > 0 &&
        expectedOutput === output.shape[axis]
      ) {
        const total = Math.max(
          0,
          (output.shape[axis] - 1) * stride + effective - input.shape[axis],
        );
        scalar(
          `pad_${suffix}`,
          Math.floor(total / 2),
          `floor(max(0, (output_${suffix} - 1) * stride_${suffix} + effective_filter_${suffix} - input_${suffix}) / 2)`,
          [
            `${same ? "SAME" : "VALID"} padding; total ${suffix} padding ${total}; leading padding shown.`,
            paddingFile,
          ],
        );
      }
    }
  }
  const loops: Record<string, [string, string]> = {
    batch: ["batches", "Batch index"],
    out_y: ["output_height", "Output row index"],
    out_x: ["output_width", "Output column index"],
    out_channel: ["output_depth", "Output channel index"],
    in_channel: [
      isDepthwise ? "input_depth" : "filter_input_depth",
      "Input channel index",
    ],
    filter_y: ["filter_height", "Filter row index"],
    filter_x: ["filter_width", "Filter column index"],
    ...(isDepthwise
      ? {
          m: ["depth_multiplier", "Depth multiplier index"] as [string, string],
        }
      : {}),
  };
  if (loops[name] && (isDepthwise ? name !== "out_channel" : true)) {
    const [bound, description] = loops[name];
    const value = fixed.get(bound)?.value;
    return {
      kind: "loop",
      description: `${description}; changes as the source loop iterates.`,
      range: `0 ≤ ${name} < ${value || bound}`,
      expression: `for (${name} = 0; ${name} < ${bound}; ++${name})`,
      evidence: [
        value
          ? `${bound} = ${value} for node ${node.index}`
          : `Loop bound: ${bound}`,
        "Declared source-loop range; no current iteration or trip count is recorded.",
      ],
    };
  }
  if (fixed.has(name)) return fixed.get(name)!;
  const varying: Record<string, string> = {
    acc: "Accumulator. Changes with products, bias, requantization, and activation clamping.",
    input_val:
      "Input tensor element selected by the current batch, spatial position, and channel.",
    filter_val:
      "Filter tensor element selected by the current filter position and channel.",
    in_x: "Input column computed from the output position, stride, padding, dilation, and filter column.",
    in_y: "Input row computed from the output position, stride, padding, dilation, and filter row.",
    in_x_origin: "Input column origin for the current output column.",
    in_y_origin: "Input row origin for the current output row.",
    is_point_inside_image: "Padding check for the current input coordinates.",
    ...(isDepthwise
      ? {
          output_channel:
            "Output channel computed as m + in_channel * depth_multiplier.",
        }
      : {
          group: "Convolution group computed from the current output channel.",
        }),
  };
  if (varying[name])
    return {
      kind: "varying",
      description: varying[name],
      evidence: [
        "PC histograms do not record intermediate values or loop iterations.",
      ],
    };
  return unavailable(
    "No scalar value is available for this variable. Tensor contents, pointers, and per-channel scaling arrays are not recorded as runtime values.",
  );
}
