# Project evaluation index

## Midterm ISA evaluation

The [midterm evaluation guide](midterm-submission.md) describes the workload,
checkpoint definitions, verification, benchmark commands, and measurement
boundaries. The [root README](../README.md#midterm-submission) provides the
source/deliverable index and expected instruction counts.

**Presentation:** [Quantized Neural-Network Acceleration on RV64IMC](https://docs.google.com/presentation/d/1C1yH6lDG07P288sPAHhANP2DuaQ6jViiKXMT8TjxvKU/edit?usp=sharing).

| Evaluation component | Evidence |
|---|---|
| Workload and model | [Bare-metal application](../tflm/efficientnet_lite0.cc), [model provenance](../models/README.md) |
| Software implementation | [SALT compiler](../compiler/), [kernels](../kernels/), [software analysis](B1-software-report.md) |
| ISA design and implementation | [Design map](../DESIGN.md), [ISA analysis](hardware-optimization-report.md), [Spike extensions](../tools/) |
| Functional verification | [Short ISA suites](midterm-submission.md#expected-results-and-verification), [compiler tests](../tests/compiler/) |
| Full-model ISA measurements | [Midterm results](../results/midterm/README.md), [benchmark commands](../EXPERIMENTS.md) |

`gmake midterm-tests` runs the short instruction suites, `gmake midterm-benchmark`
performs full-workload evaluation, and `gmake midterm-report` regenerates the
ISA-only comparison from retained evidence. These targets use Spike and require
no RTL snapshots or PPA tools. The [midterm scope](midterm-requirements.md) is
separate from the extended RTL evaluation below.

## Extended RTL and hardware-cost evaluation

The [combined Spike/RTL results](../results/submission/README.md) connect the
software progression to the accepted X1–X5 configurations and their archived
CV-Wally measurements.

| Component | Source and evidence |
|---|---|
| CV-Wally implementation | [RTL guides](../DESIGN.md), `rtl/`, `tools/cvw/` |
| Full-model simulation | [Baseline and software](../results/cvw/baseline/README.md), [packed MAC/requantization](../results/cvw/full-custom/README.md), [post-increment](../results/cvw/full-postinc/README.md), [depthwise bank](../results/cvw/full-dwmac/README.md), [packed stem](../results/cvw/full-x5/README.md) |
| Cycle/CPI comparisons | [Hardware-era results](../results/profiling/hardware-progression/README.md) |
| Synthesis configuration and scripts | [Synthesis workflow](../synth/README.md), `synth/configs/`, `synth/scripts/`, `synth/tcl/` |
| Hardware-cost measurement status | [Recorded DC startup failure](../results/synthesis/baseline/README.md); mapped area and physical Fmax are unavailable |

Full-model RTL simulations cover A0 (historical `B0`), accepted B1, and X1–X5.
D1 and intermediate compiler substages have no separate full-model cycle
measurements. X4 and X5 use the same RTL configuration; X5 changes only the stem
software. The main X4 comparison includes D1's software correction, while the
ISA-only ablation compares D1 directly with X4.

RTL cycles and CPI describe the recorded simulated processor. Physical frequency,
area, and speedup/area require completed synthesis evidence and cannot be inferred
from instruction counts or the available RTL cycles. The
[term-project assignment](../instructions.md) defines the broader hardware-cost
and final-report scope.

## Reproduction and evidence packaging

[EXPERIMENTS.md](../EXPERIMENTS.md) indexes the individual software, ISA, RTL, and
synthesis commands. `gmake submission-report` regenerates the combined results
when the selected raw Spike captures and archived RTL snapshots are available.
RTL execution and collection use the pinned Linux/WSL workflow in the
[simulation guide](cvw-verilator.md).

`gmake submission-package` creates a local source/evidence archive, file manifest,
and checksum under `build/submission/`. It includes compact results, selected
immutable Spike captures, frozen LiteRT profiles, and archived RTL snapshots.
Downloaded dependencies/toolchains and machine-specific access settings are
excluded. Every packaged file is checked against its SHA-256 manifest.

Raw captures and generated builds are excluded from Git. The benchmark workflows
regenerate compiler/native evidence; archived RTL data is supplied separately
for combined-report validation. The midterm Spike-only workflow has no dependency
on that RTL data.
