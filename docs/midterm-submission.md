# Midterm evaluation guide

This evaluation measures the effect of software specialization and custom
instructions on full EfficientNet-Lite0 inference using Spike. It includes a
bare-metal reference, cumulative software checkpoints, four ISA mechanisms,
instruction verification, and full-model retirement profiles. Evaluation scope
is defined by the [midterm requirements](midterm-requirements.md),
[assignment](../instructions.md), and [clarifications](../clarifications.md).

**Presentation:** [Quantized Neural-Network Acceleration on RV64IMC](https://docs.google.com/presentation/d/1C1yH6lDG07P288sPAHhANP2DuaQ6jViiKXMT8TjxvKU/edit?usp=sharing).

## Deliverables

| Deliverable | Entry points |
|---|---|
| Bare-metal C/C++ workload | [LiteRT application](../tflm/efficientnet_lite0.cc), [RV64IMC platform](../tflm/platform/rv64imc/README.md), [SALT compiler](../compiler/), [inference kernels](../kernels/) |
| Quantized model | [Model file](../models/efficientnet-lite0-int8.tflite), [provenance and quantization](../models/README.md) |
| Spike/custom ISA source | [Xqmac8](../tools/xqmac8/extension.cc), [Xrequant](../tools/xrequant/extension.cc), [Xpostinc](../tools/xpostinc/extension.cc), [Xdwmac8](../tools/xdwmac8/extension.cc), [profiler](../tools/spike_profile/) |
| Instruction verification | [Packed MAC](../tools/xqmac8/test.py), [requantization](../tools/xrequant/test.py), [post-increment](../tools/xpostinc/test.py), [depthwise bank](../tools/xdwmac8/test.py) |
| Full-workload benchmarks | [Software configurations and workflow](../experiments/README.md), [ISA configurations and workflow](../experiments/hardware.md), [midterm reporter](../tools/report_midterm.py) |
| Results and design analysis | [Expected measurements](../results/midterm/README.md), [baseline bottlenecks](../results/profiling/B0/analysis.md), [software analysis](B1-software-report.md), [ISA analysis](hardware-optimization-report.md) |

## Workload and checkpoint definitions

EfficientNet-Lite0 contains 4,631,000 learned parameters and performs 385,187,552
logical MACs across 64 operators. Its compute core uses signed INT8 weights and
activations with INT32 biases/accumulators. Public UINT8 input/output is retained
through the model's two boundary conversions. Shapes, quantization parameters,
and the model SHA-256 are recorded in the [model audit](../models/README.md).

| Evaluation label | Implementation |
|---|---|
| A0 | LiteRT Micro interpreter and reference kernels; historical evidence directory `B0` |
| B1.1 | SALT static graph preparation and C++ generation; historical compiler configuration `A0` |
| B1.2–B1.7 | Cumulative pointwise, depthwise, stem/runtime, requantization, and spatial-blocking optimizations |
| X1 | Packed pointwise MAC with alignment/register/tile refinements; source checkpoint `X1-tile2x4` |
| X2 | Exact hardware requantization with outlining/register refinements; source checkpoint `X2-optimized` |
| X3 | Selected post-increment addressing; source checkpoint `X3-selected` |
| X4 | Depthwise accumulator bank following D1 software zero-point correction |
| X5 | RGB stem restructuring using the existing packed-MAC ISA |

B1.4 stem unrolling is measured separately and grouped into B1.5 in the main
comparison. X3.broad is an alternative to selected X3, and D1 isolates the
software contribution before X4. The manifests preserve each comparison parent;
the supporting trials are not additional steps in the main progression.

## Reproduce the evaluation

The [host setup](../README.md#build-and-run) targets macOS on Apple Silicon with
Xcode Command Line Tools, GNU Make, Python, `uv`, `dtc`, and Boost. Dependencies
and the RISC-V toolchain are pinned in the Makefile. Linux/Intel hosts require
corresponding SDK/toolchain configuration.

Run sequentially from the repository root:

```sh
gmake run-native
gmake run-spike
gmake midterm-tests
gmake midterm-benchmark
```

Native setup downloads the third-party headers reused by the RISC-V build.
`run-spike` checks the bare-metal reference output. `midterm-tests` runs the
short ISA suites and report-integrity checks. `midterm-benchmark` evaluates the
complete model through the software and custom-ISA sequence, including a fresh
LiteRT baseline, and writes [results/midterm/](../results/midterm/README.md).

The benchmark reuses existing captures only after validating their build inputs,
correctness evidence, model/input identity, and provenance. Missing captures are
regenerated with native/intermediate/sanitizer comparison, ordinary Spike, and
two complete event/PC profiles. Full evaluation can take substantial time.

| Command | Purpose | Result |
|---|---|---|
| `gmake midterm-tests` | Short tests of the custom instructions and report-integrity rules | Per-suite `PASS` output |
| `gmake midterm-baseline` | Remeasure LiteRT without replacing the frozen `B0` reference | `results/profiling/midterm-A0/` |
| `gmake midterm-benchmark` | Full software/custom-ISA evaluation | `results/midterm/` |
| `gmake midterm-report` | Revalidate retained compiler captures against the frozen LiteRT reference | `results/midterm/` |

The midterm targets use Spike and do not depend on CV-Wally, archived RTL
snapshots, or synthesis tools. The separate `hardware-experiments` and
`submission-report` targets include the extended RTL evidence.

## Expected results and verification

| Configuration | Retired instructions per full inference |
|---|---:|
| A0: LiteRT Micro | 4,867,278,370 |
| B1.7: optimized software | 1,576,585,275 |
| X5: final custom-ISA configuration | 167,729,178 |

[The complete comparison](../results/midterm/README.md) contains all twelve main
checkpoints. Its CSV includes the instruction mix, MAC/instruction, load/store
instructions per MAC, custom-instruction frequency, and executable code size.

Expected public output:

```text
output_top_index=21 output_top_score=48 output_sum=215
output_fnv1a=0x4b6a91e2
```

| ISA suite | Vector coverage | Additional checks |
|---|---:|---|
| Xqmac8 | 10,852 | Register aliases, zero register, accumulation chains, traps, disassembly, ordinary/profile agreement, native sanitizers |
| Xrequant | 12,256 | Independent/pinned-reference comparison, rounding/clipping cases, 64-step chain, 18 traps, repeat profiles, native sanitizers |
| Xpostinc | 12,672 | Memory widths/strides, aliases, 35 precise faults, disabled-extension/RV32 behavior, repeat profiles |
| Xdwmac8 | 10,256 | Bank arithmetic, state transfers, context restore, aliases, traps, hart isolation, repeat profiles |

Generated checkpoints compare all 1,000 public output bytes. The native suite
also checks intermediate tensors and sanitizers across eight oracle cases,
including the reference's known rejected Softmax domain. The LiteRT baseline
collector checks the reference checksum.

The [X1 replay](../results/profiling/X1-tile2x4-replay/README.md) supplies
scalar/packed dot-product microbenchmarks and two major pointwise operators.
[The X2 replay](../results/profiling/X2-optimized-replay/README.md) adds depthwise,
ADD, and further pointwise measurements. The
[baseline analysis](../results/profiling/B0/analysis.md) relates the instruction
mix and operator costs to scalar arithmetic, memory/address, and requantization
bottlenecks.

## Measurement boundaries and evidence

Counts cover invocation entry through its returning instruction, including
wrappers and callees. Allocation, input preparation, output verification, and
printing are excluded. The canonical input uses seed 1. Two full event/PC
profiles must agree; 64 inclusive execution units plus invocation overhead
partition each generated inference count.

`validation.json` identifies the baseline summary, capture IDs, manifest hashes,
and acceptance checks. The default report uses the frozen LiteRT reference;
`midterm-benchmark` measures a separate fresh baseline. Large raw captures,
ELFs, and native build evidence reside under ignored `build/`; benchmark commands
regenerate them on a clean checkout. Compact results are included in Git.

Instruction reductions and ratios describe ISA-level work. They do not establish
cycle speedup, physical timing, cache misses, or external bandwidth. The
synthetic-input comparisons establish implementation equivalence rather than
dataset classification accuracy. [RTL measurements](submission.md) are a
separate evaluation, outside the midterm scope.
