# EfficientNet-Lite0 on RV64IMC

This project evaluates software and custom-ISA optimization of full W8A8
EfficientNet-Lite0 inference on bare-metal RV64IMC. LiteRT Micro supplies the
frozen reference and oracle; SALT statically lowers the fixed graph. Spike
measures ISA-level work and CV-Wally supplies full-model RTL cycle simulation.

## Midterm submission

**Presentation:** [Quantized Neural-Network Acceleration on RV64IMC](https://docs.google.com/presentation/d/1C1yH6lDG07P288sPAHhANP2DuaQ6jViiKXMT8TjxvKU/edit?usp=sharing).
Google Drive confirms **anyone with the link can view** (checked 2026-10-27).
The midterm scope in the [assignment](instructions.md#9-grading-policy) is
ISA design and Spike with custom instructions; RTL/synthesis evidence is
provided separately for the later hardware evaluation.

| Item | Source, explanation and evidence |
|---|---|
| Workload and quantized model | [EfficientNet-Lite0 `.tflite`](models/efficientnet-lite0-int8.tflite), [provenance/quantization audit](models/README.md), [machine-readable audit](models/efficientnet-lite0-int8.audit.json) |
| Bare-metal reference and optimized implementation | [LiteRT application](tflm/efficientnet_lite0.cc), [RV64IMC startup/linker/platform](tflm/platform/rv64imc/README.md), [SALT compiler](compiler/), [kernels](kernels/), [compiler guide](docs/compiler.md) |
| Baselines and cumulative software changes | [A0 baseline analysis](results/profiling/B0/analysis.md), [software report](docs/B1-software-report.md), [B1.1–B1.7 configurations](experiments/software.json), [measured software results](results/profiling/B1-reordered/README.md) |
| ISA semantics and encodings | [Xqmac8 packed MAC](docs/xqmac8.md), [Xrequant exact scaling](docs/xrequant.md), [Xpostinc addressing](docs/xpostinc.md), [Xdwmac8 depthwise bank](docs/xdwmac8.md); [grouped progression and software/ISA attribution](docs/hardware-optimization-report.md) |
| Spike implementation | [Pinned simulator revision/build](Makefile), [Xqmac8 plugin](tools/xqmac8/extension.cc), [Xrequant plugin](tools/xrequant/extension.cc), [post-increment implementation](tools/xpostinc/), [depthwise implementation](tools/xdwmac8/), [profiling patch/collector](tools/spike_profile/) |
| Correctness and ISA verification | [Compiler tests](tests/compiler/), [Xqmac8 verification](results/xqmac8/verification.json), [Xrequant verification](results/xrequant/verification.json), [post-increment verification](results/xpostinc/verification.json), [depthwise-bank verification](results/profiling/X4-verification.md), [hardware-era capture validation](results/profiling/hardware-progression/validation.json) |
| Microbenchmarks and major operators | [Scalar/packed dot products and pointwise nodes 4/58](results/profiling/X1-tile2x4-replay/README.md), [depthwise/ADD/pointwise replay](results/profiling/X2-optimized-replay/README.md), [depthwise and stem replay](results/profiling/X5-replay/README.md) |
| Quantitative results and bottlenecks | [Complete progression/charts](results/submission/README.md), [instruction mix and MAC ratios](results/profiling/hardware-progression/instruction-mix.csv), [operator costs](results/profiling/hardware-progression/operators.csv), [custom utilization](results/profiling/hardware-progression/custom-utilization.csv), [code/data sizes](results/profiling/hardware-progression/footprint.csv) |
| Reproduction and measurement boundaries | [Build/run below](#build-and-run), [software workflow](experiments/README.md), [ISA workflow](experiments/hardware.md), [Baseline profiling contract](docs/profiling.md), [compiler profiling contract](docs/compiler-profiling.md), [command index](EXPERIMENTS.md) |
| Written midterm report | [Report source](reports/midterm/main.tex) and [report guide/status](reports/midterm/README.md); **the source is still a placeholder scaffold, not a completed report** |
| AI assistance disclosure | [AI_USAGE.md](AI_USAGE.md); earlier-use disclosure still needs author completion |

For a quick review, open the slides, [unified results](results/submission/README.md)
and [architecture narrative](docs/hardware-optimization-report.md). For execution,
follow [Build and run](#build-and-run) first, then the commands in
[EXPERIMENTS.md](EXPERIMENTS.md). Large raw captures and toolchains live outside
Git; the local `submission-package` archive includes the selected raw evidence,
while dependencies and local access settings are excluded.

After the initial native/Spike setup below, run `gmake compiler-x1-tests` and
`gmake compiler-x2-tests` for the required packed-MAC/requantization ISA gates,
or `gmake hardware-tests` for the full compiler, ISA, profiler and offline RTL
gate set. These tests are separate from rerunning full-inference measurements.

Start with the [submission evidence package](results/submission/README.md),
[design map](DESIGN.md), [experiment index](EXPERIMENTS.md) and
[deliverable checklist](docs/submission.md). The main progression is:

```text
A0 → B1.1 → B1.2 → B1.3 → B1.5 → B1.6 → B1.7 → X1 → X2 → X3 → X4 → X5
```

The [software report](docs/B1-software-report.md) retains separately measured
B1.4 stem unrolling, grouped with B1.5 in the main presentation. The
[hardware-era report](docs/hardware-optimization-report.md) retains X1.1–X1.4,
X2.1–X2.3, broad/selected X3 trials, and D1's software-only correction before X4.

Submission **A0** is the LiteRT Micro baseline; **B1.1** introduces the SALT custom compiler.
Historical evidence paths and low-level targets retain `B0` for LiteRT and
compiler configuration `A0` for SALT. Accepted **B1** means **B1.7**.

Main X1 means the final `X1-tile2x4` configuration; main X2 means
`X2-optimized`. Historical folders named `X1` and `X2` are their initial ISA
substages, not the final presentation configurations. X5 introduces no new ISA.

[Software configuration](experiments/software.json) and
[hardware configuration](experiments/hardware.json) drive repeatable workflows:

```sh
gmake software-experiments
gmake hardware-experiments
gmake submission-report
```

`gmake submission-package` builds a checksummed local source/evidence archive
under `build/submission/`, including the selected frozen captures and RTL
snapshots. Dependencies and machine-specific access settings are excluded.

The software workflow reruns the reordered cumulative experiments. The hardware
workflow revalidates retained captures because its accepted order is unchanged;
`gmake hardware-recapture` explicitly creates separate fresh Spike captures.
X2.2's outlining-only result has been remeasured through the production compiler.
See [software setup](experiments/README.md) and
[hardware setup and RTL evidence](experiments/hardware.md).

Accepted B1 retires 1,576,585,275 instructions; X5 retires 167,729,178. The saved
RTL runs measure 1,679,179,098 and 239,303,116 simulated cycles respectively.
The reports keep instruction-count ratios, simulated cycle speedup and physical
performance distinct. Area/Fmax remain unavailable because
[synthesis is blocked at DC startup](results/synthesis/baseline/README.md).
The [assignment](instructions.md) and [clarifications](clarifications.md) define
the deliverables. The midterm presentation is linked above; the written midterm
report remains a scaffold, and final report/presentation requirements are tracked
separately in [the submission checklist](docs/submission.md).

## Start here

| Location | What to read or change |
|---|---|
| [models/README.md](models/README.md) | Model provenance, quantization, operator inventory, and constraint audit |
| [tflm/efficientnet_lite0.cc](tflm/efficientnet_lite0.cc) | Application entry point: register operators, prepare tensors, fill input, invoke, report output |
| [tflm/README.md](tflm/README.md) | Runtime flow, reference kernels, memory use, and floating-point setup details |
| [tflm/platform/rv64imc/README.md](tflm/platform/rv64imc/README.md) | Startup, memory layout, Spike console/exit protocol, and platform hooks |
| [Makefile](Makefile) | Dependency versions, host build, RISC-V cross compilation, and simulation commands |
| [experiments/README.md](experiments/README.md) | Cumulative A0 baseline and B1.1–B1.7 runner, correctness, repeated profiling and resume workflow |
| [EXPERIMENTS.md](EXPERIMENTS.md) | Software, ISA, RTL and synthesis command/evidence index |
| [results/submission/README.md](results/submission/README.md) | Unified progression, instruction chart and links to measured controls and cycles |
| [docs/hardware-optimization-report.md](docs/hardware-optimization-report.md) | Grouped X1–X5 narrative, compiler substages, D1 ablation and RTL attribution |
| [docs/submission.md](docs/submission.md) | Required deliverables, available evidence and remaining final artifacts |
| [tools/README.md](tools/README.md) | Model inspection, model embedding, and ELF audit utilities |
| [docs/profiling.md](docs/profiling.md) | Reproducible retirement profiling, boundaries, validation, and future comparisons |
| [results/profiling/B0/README.md](results/profiling/B0/README.md) | Validated baseline metrics and links to bottleneck analysis |
| [docs/B1-software-report.md](docs/B1-software-report.md) | Accepted software B1, every optimization, repeated profiles, code/memory costs and reproduction |
| [docs/xqmac8.md](docs/xqmac8.md) | X1 packed INT8 MAC contract, Spike integration, correctness and incremental measurements |
| [docs/cvw-verilator.md](docs/cvw-verilator.md) | Preserved B0/B1 execution on CV-Wally in Windows WSL2, verification and cycle measurement |
| [synth/README.md](synth/README.md) | NTHU remote ASIC synthesis setup, registered-adder smoke validation, jobs, reports and comparison |

Downloaded sources, toolchains, and environments live in `.deps/`. Embedded
model arrays live in `tflm/generated/`. Simulator output lives in `build/`.
These directories are ignored by Git; their source inputs and generation
commands are tracked.

## Build and run

The supplied build configuration targets **macOS on Apple Silicon**. It uses
`xcrun` for the native compiler SDK and downloads the Darwin ARM64 xPack
toolchain. A Linux or Intel Mac port needs corresponding host/toolchain
configuration changes. The RISC-V program itself targets `rv64imc` with the
`lp64` ABI.

Install Xcode Command Line Tools if needed, and ensure Python 3 with `venv`
and `pip` is available. With Homebrew installed, the remaining build
prerequisites are:

```bash
xcode-select --install  # Only if the developer tools are not already installed.
brew install make dtc boost python uv
```

From the repository root, run:

```bash
gmake run-native
gmake run-spike
```

Use GNU Make (`gmake`) for the top-level Makefile as well as the upstream
build; it uses grouped targets for the generated model files. **Run the
native command first on a fresh checkout:** it downloads TFLM's third-party
dependencies, which the RV64 target currently reuses with `SKIP_DOWNLOADS=1`.
The first build also downloads the pinned TFLM sources, creates a Python
environment with Pillow for upstream build scripts, downloads the RISC-V
toolchain, and builds the pinned Spike simulator. Network access is needed
for this setup.

`run-spike` builds the ELF, screens its ISA attributes and disassembly for
floating-point/vector/atomic instructions, runs Spike with `--isa=rv64imc`,
and checks the expected output fields:

```text
TFLM EfficientNet-Lite0 inference: PASS
arena_used_bytes=1688176
output_top_index=21 output_top_score=48 output_sum=215
output_fnv1a=0x4b6a91e2
Spike output matches the native TFLM reference: PASS
```

The input is a fixed sequence of pseudo-random bytes. This checks execution
and reproducibility; it does not measure classification accuracy on images.
The top index is a zero-based output index and the score is a raw quantized
byte. The checksum covers all 1,000 output bytes.

## Other useful commands

| Command | Purpose |
|---|---|
| `gmake native` | Build the host executable without running it |
| `gmake model-data` | Embed the tracked `.tflite` as an aligned C++ byte array |
| `gmake rv64` | Cross compile the bare-metal executable; run `run-native` first on a fresh checkout |
| `gmake audit-rv64` | Build and inspect the RISC-V ELF without simulating it |
| `gmake spike` | Build/install the pinned host-side Spike simulator |
| `gmake run-spike JOBS=4` | Run the workflow with fewer parallel build jobs |
| `gmake clean-local` | Move generated model arrays to a temporary directory for regeneration |

`clean-local` only moves `tflm/generated/`; it does not clean the upstream
object files or downloaded dependencies.

Important generated outputs:

```text
tflm/generated/model_data.{cc,h}                            embedded model
.deps/tflite-micro/gen/osx_arm64_release_with_logs_gcc/bin/
  efficientnet_lite0                                       native executable
.deps/tflite-micro/gen/rv64imc_rv64imc_release_with_logs_gcc/bin/
  efficientnet_lite0                                       RISC-V ELF
.deps/spike/bin/spike                                      host simulator
build/spike-output.txt                                     latest verified output
```

## What runs where

The host converts the model file into a C++ array and compiles the application,
TFLM runtime, reference kernels, and platform support into one RISC-V ELF.
The array preserves the original FlatBuffer graph; TFLM interprets that graph
on the target. Spike loads the ELF and executes its RISC-V instructions,
including both `AllocateTensors()` and `Invoke()`.

The model has 4,631,000 learned parameters and an estimated 385,187,552 MACs
per inference. Its computational core uses signed INT8 weights and
activations with INT32 biases/accumulators. The public input and output are
UINT8, with integer conversions at the graph boundaries.

`AllocateTensors()` prepares each operator and computes fixed-point
requantization multipliers from floating-point scale metadata. In this build,
those setup calculations use software floating-point helpers compiled to
integer instructions. `Invoke()` uses integer kernels, including integer
requantization and quantized softmax. No floating-point hardware is required.
See [the runtime guide](tflm/README.md#setup-and-inference-arithmetic) for details.

## Interpreting the baseline

TFLM plans its buffers inside a static 2 MiB arena; the verified run uses
1,688,176 bytes. The linker maps 128 MiB of RAM at `0x80000000` and reserves
a 1 MiB stack. That address-space provision is not the measured RAM usage.
The model is also embedded in the ELF's read-only data.

The ELF audit's decoded instruction count is a **static code count**. The
[A0 baseline profile](results/profiling/B0/README.md) measures 4,867,278,370 dynamic
instructions per `Invoke()`, separately from allocation, input generation, and
console reporting. It records instruction mix, per-layer contribution, and
MAC/instruction. Spike provides ISA execution; CV-Wally RTL is needed for
hardware cycle counts and CPI.

The accepted software B1 is the comparison baseline for ISA experiments. Build
it with `gmake compiler-b1-software-build`, validate it with
`gmake compiler-b1-software-verify`, or run correctness and repeated full profiling
with `gmake compiler-b1-software-checkpoint`. The
[report](docs/B1-software-report.md) includes intermediate-output coverage,
representative replays and remaining bottlenecks. Keep exact reference checks
as kernels change; synthetic-input equivalence does not establish dataset accuracy.

## Interactive model-to-assembly explorer

[Execution Atlas](docs/explorer.md) connects each model operator to its measured
RISC-V instructions, C++ source, hot loops, and optional verified GCC intermediates.
Run `npm ci --prefix explorer`, `gmake explorer-export`, then `gmake explorer-dev`.
Use `gmake explorer-compiler` followed by `gmake explorer-export` to attach compiler
evidence. The viewer runs locally and also accepts portable profile ZIPs.

For live instruction stepping, registers, memory, and stage-aware breakpoints,
see the **Simulator** tab in [Execution Atlas](docs/simulator.md). Run
`gmake app-serve` (or `gmake simulator-serve`) and open **http://127.0.0.1:8765/**
for both tabs and the local simulation backend. `gmake app-dev` starts the combined
development app on port 5174. Switching tabs preserves each workspace's state;
profile selections and simulator execution remain independent.
