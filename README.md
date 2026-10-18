# EfficientNet-Lite0 on RV64IMC

This project studies architectural extensions for quantized neural-network
inference on a bare-metal RV64IMC processor. The selected workload is
EfficientNet-Lite0, with a frozen LiteRT Micro reference and a fixed-model
compiler (the upstream repository and code still use the names TFLite Micro
and TFLM). Spike executes the compiled RISC-V program. The eventual hardware
target is CV-Wally.

The implementation runs full-model inference on the host and in Spike, with
matching output checksums for one deterministic input. The reproducible B0
instruction-profiling workflow is described in [docs/profiling.md](docs/profiling.md).
The accepted [software B1 report](docs/B1-software-report.md) documents owned
scalar kernels and their optimization history. Fresh repeated profiles measure
1,576,585,275 instructions: 60.39% fewer than corrected A0 and 67.61% fewer than
B0. Custom MAC/requantization instructions and RTL evaluation remain future work.
The [fixed-model compiler guide](docs/compiler.md) documents the frozen B0,
native tensor oracle, graph importer, exact integer preparation, static memory
planner, standalone A0 reference execution, and known reference limitation.
See [instructions.md](instructions.md) for the assignment requirements and
[clarifications.md](clarifications.md) for additional guidance.

## Start here

| Location | What to read or change |
|---|---|
| [models/README.md](models/README.md) | Model provenance, quantization, operator inventory, and constraint audit |
| [tflm/efficientnet_lite0.cc](tflm/efficientnet_lite0.cc) | Application entry point: register operators, prepare tensors, fill input, invoke, report output |
| [tflm/README.md](tflm/README.md) | Runtime flow, reference kernels, memory use, and floating-point setup details |
| [tflm/platform/rv64imc/README.md](tflm/platform/rv64imc/README.md) | Startup, memory layout, Spike console/exit protocol, and platform hooks |
| [Makefile](Makefile) | Dependency versions, host build, RISC-V cross compilation, and simulation commands |
| [tools/README.md](tools/README.md) | Model inspection, model embedding, and ELF audit utilities |
| [docs/profiling.md](docs/profiling.md) | Reproducible retirement profiling, boundaries, validation, and future comparisons |
| [results/profiling/B0/README.md](results/profiling/B0/README.md) | Validated baseline metrics and links to bottleneck analysis |
| [docs/B1-software-report.md](docs/B1-software-report.md) | Accepted software B1, every optimization, repeated profiles, code/memory costs and reproduction |
| [docs/xqmac8.md](docs/xqmac8.md) | X1 packed INT8 MAC contract, Spike integration, correctness and incremental measurements |
| [docs/cvw-verilator.md](docs/cvw-verilator.md) | Preserved B0/B1 execution on CV-Wally in Windows WSL2, verification and cycle measurement |

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
brew install make dtc boost python
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
[B0 profile](results/profiling/B0/README.md) measures 4,867,278,370 dynamic
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
