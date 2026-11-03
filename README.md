# EfficientNet-Lite0 on RV64IMC

This project evaluates software and custom-ISA acceleration of W8A8
EfficientNet-Lite0 inference on bare-metal RV64IMC. LiteRT Micro provides the
reference implementation; the SALT custom compiler prepares the fixed graph and
emits specialized C++ kernels. Spike measures the instruction cost of each
software and ISA checkpoint.

Full inference retires **4,867,278,370 instructions** with LiteRT Micro,
**1,576,585,275** with optimized software, and **167,729,178** with the final
custom-ISA implementation. These are instruction-count measurements on a
fixed synthetic input; they do not represent execution-time speedup.

## Midterm submission

**Presentation:** [Quantized Neural-Network Acceleration on RV64IMC](https://docs.google.com/presentation/d/1C1yH6lDG07P288sPAHhANP2DuaQ6jViiKXMT8TjxvKU/edit?usp=sharing).

The midterm evaluation covers the bare-metal workload, software optimizations,
custom instructions, functional verification, and full-model ISA measurements.
The [evaluation guide](docs/midterm-submission.md) describes the experiments,
expected outputs, and measurement boundaries. RTL and PPA evaluation are outside
the midterm scope; additional RTL results are documented separately below.

| Deliverable | Source and documentation |
|---|---|
| Bare-metal C/C++ workload | [LiteRT application](tflm/efficientnet_lite0.cc), [startup/linker/platform](tflm/platform/rv64imc/README.md), [SALT compiler](compiler/), [optimized kernels](kernels/), [compiler guide](docs/compiler.md) |
| Quantized model | [EfficientNet-Lite0 `.tflite`](models/efficientnet-lite0-int8.tflite), [model provenance and quantization](models/README.md), [machine-readable model audit](models/efficientnet-lite0-int8.audit.json) |
| Spike/custom ISA implementation | [Packed MAC](tools/xqmac8/extension.cc), [requantization](tools/xrequant/extension.cc), [post-increment](tools/xpostinc/extension.cc), [depthwise bank](tools/xdwmac8/extension.cc), [retirement profiler](tools/spike_profile/), [pinned builds](Makefile) |
| Instruction verification | [Packed-MAC tests](tools/xqmac8/test.py), [requantization tests](tools/xrequant/test.py), [post-increment tests](tools/xpostinc/test.py), [depthwise-bank tests](tools/xdwmac8/test.py); run `gmake midterm-tests` |
| Reproducible full-workload benchmarks | [Software configurations](experiments/software.json), [ISA configurations](experiments/hardware.json), [experiment index](EXPERIMENTS.md); run `gmake midterm-benchmark` |
| Measurements and analysis | [Midterm results](results/midterm/README.md), [baseline bottlenecks](results/profiling/B0/analysis.md), [software analysis](docs/B1-software-report.md), [ISA analysis](docs/hardware-optimization-report.md) |

## Evaluation summary

| Checkpoint | Change | Retired instructions per inference |
|---|---|---:|
| A0 | LiteRT Micro baseline | 4,867,278,370 |
| B1.1 | Custom compiler (SALT) | 3,980,184,493 |
| B1.2 | Pointwise specialization | 2,728,312,505 |
| B1.3 | Depthwise specialization | 2,388,006,921 |
| B1.5 | Stem unrolling and runtime cleanup | 2,155,543,452 |
| B1.6 | Requantization specialization | 2,009,370,040 |
| B1.7 | Spatial 2×2 blocking | 1,576,585,275 |
| X1 | Packed pointwise MAC | 594,975,670 |
| X2 | Hardware requantization | 436,158,109 |
| X3 | Selected post-increment | 423,520,020 |
| X4 | Packed depthwise MAC with D1 correction | 229,114,977 |
| X5 | Packed RGB stem using existing ISA | 167,729,178 |

The sequence is cumulative. B1.4 stem unrolling is measured separately and
grouped into B1.5 in this table. X1 and X2 include their compiler refinements;
X4 includes the D1 software zero-point correction. X5 reuses the existing ISA.
[Detailed results](results/midterm/progression.csv) include the instruction mix,
MAC/instruction, load/store instructions per MAC, custom-instruction frequency,
and executable code size.

The evaluation labels are distinct from historical implementation names:
A0 uses the LiteRT evidence stored as `B0`; B1.1 uses compiler configuration
`A0`; and B1.7 is also called accepted `B1`. Main X1 is `X1-tile2x4`, main X2
is `X2-optimized`, and main X3 is `X3-selected`. The configuration manifests
retain these mappings and the original capture identities.

## Build and run

The automatic setup targets **macOS on Apple Silicon**. It uses the Xcode
Command Line Tools SDK and the pinned Darwin ARM64 xPack RISC-V toolchain.
Other hosts require corresponding SDK/toolchain configuration. Target programs
use `rv64imc` and the `lp64` ABI.

Install the host prerequisites:

```sh
xcode-select --install  # If the Xcode Command Line Tools are not installed.
brew install make dtc boost python uv
```

Run the evaluation commands sequentially from the repository root:

```sh
gmake run-native
gmake run-spike
gmake midterm-tests
gmake midterm-benchmark
```

`run-native` downloads the pinned LiteRT Micro sources and third-party
prerequisites and verifies the native reference. `run-spike` cross-compiles the
bare-metal application, checks its ISA, and verifies its output on Spike. On a
fresh checkout, native setup precedes the RISC-V build because the latter reuses
the downloaded headers. Initial setup requires network access. GNU Make
(`gmake`) is required.

| Command | Evaluation performed | Output |
|---|---|---|
| `gmake midterm-tests` | Directed/random tests for all four custom-ISA mechanisms, including alias, trap/fault, context, and repeat-profile checks | Per-suite `PASS` output; test artifacts under `build/` |
| `gmake midterm-baseline` | Fresh full-model LiteRT retirement profile under the separate `midterm-A0` name | `results/profiling/midterm-A0/` |
| `gmake midterm-benchmark` | Full software/custom-ISA sequence, fresh LiteRT baseline, correctness checks, and repeated profiles | `results/midterm/` |
| `gmake midterm-report` | Revalidate saved compiler captures against the frozen LiteRT reference | `results/midterm/` |

The full benchmark builds missing checkpoints and reuses matching captures only
after validation. It can take substantial time. `midterm-report` requires the
raw captures and native build evidence produced by the benchmark; the published
result tables can be read without regenerating those files. The midterm commands
run independently of CV-Wally and synthesis tools.

Expected baseline output:

```text
TFLM EfficientNet-Lite0 inference: PASS
arena_used_bytes=1688176
output_top_index=21 output_top_score=48 output_sum=215
output_fnv1a=0x4b6a91e2
Spike output matches the native TFLM reference: PASS
```

Generated checkpoints compare all 1,000 public output bytes against the
reference. The native correctness suite also compares intermediate tensors and
runs sanitizers across eight oracle cases, including the known rejected Softmax
domain. The short instruction suites cover 10,852 packed-MAC vectors, 12,256
requantization vectors, 12,672 post-increment vectors, and 10,256 depthwise-bank
vectors, with additional instruction-specific checks.

## Workload and measurement method

EfficientNet-Lite0 has **4,631,000 learned parameters**, **64 operators**, and
**385,187,552 logical MACs** per inference. Internal weights and activations are
signed INT8, with INT32 biases/accumulators. Public input and output are UINT8;
two graph-boundary conversions preserve the original model interface. The
[model audit](models/README.md) documents shapes, quantization, and provenance.

Retirement counts cover invocation entry through the returning instruction,
including wrappers and callees. Allocation, input generation, verification, and
printing are excluded. The canonical input uses seed 1. Two complete event/PC
profiles must agree, and operator costs plus invocation overhead must conserve
the total. [Baseline](docs/profiling.md) and
[compiler](docs/compiler-profiling.md) profiling contracts define the boundaries
and validation rules.

The deterministic input measures implementation equivalence and reproducibility,
not classification accuracy on an image dataset. Spike counts do not establish
cycles, cache misses, external memory traffic, or physical execution speed.
LiteRT setup uses software floating-point helpers compiled into integer
instructions; inference requires no floating-point hardware.

| Analysis | Evidence |
|---|---|
| Baseline instruction mix and bottlenecks | [Baseline analysis](results/profiling/B0/analysis.md) |
| Cumulative software changes and storage tradeoffs | [Software report](docs/B1-software-report.md), [stage-level results](results/profiling/B1-reordered/README.md) |
| ISA semantics and encodings | [Xqmac8](docs/xqmac8.md), [Xrequant](docs/xrequant.md), [Xpostinc](docs/xpostinc.md), [Xdwmac8](docs/xdwmac8.md) |
| ISA comparisons and supporting controls | [ISA report](docs/hardware-optimization-report.md), [configuration graph](experiments/hardware.json) |
| Dot-product microbenchmarks and two pointwise operators | [X1 replay](results/profiling/X1-tile2x4-replay/README.md) |
| Depthwise, ADD, and further operator measurements | [X2 replay](results/profiling/X2-optimized-replay/README.md), [X5 replay](results/profiling/X5-replay/README.md) |

## Repository map

| Location | Contents |
|---|---|
| `models/` | Quantized model, provenance, and model audit |
| `tflm/` | Bare-metal reference application and platform support |
| `compiler/`, `kernels/` | SALT graph preparation, C++ generation, and inference kernels |
| `tools/` | Spike extensions, profiling, verification, and reporting |
| `experiments/` | Explicit checkpoint configurations and reproduction workflows |
| `results/` | Measurements, validation records, tables, and figures |
| `docs/` | Evaluation methodology, implementation details, and ISA contracts |
| `explorer/` | Optional model-to-assembly explorer and live simulator interface |

[DESIGN.md](DESIGN.md) maps implementation components to source and design
notes. [EXPERIMENTS.md](EXPERIMENTS.md) indexes commands and evidence. The
[course requirements](docs/midterm-requirements.md),
[assignment](instructions.md), and [clarifications](clarifications.md) define the
evaluation scope.

Downloaded dependencies and toolchains reside in `.deps/`. Generated model
arrays reside in `tflm/generated/`; executables and raw captures reside in
`build/`. These directories are ignored by Git and are generated by the build
and benchmark commands. Compact measurements and provenance are included in
the repository.

## Interactive model-to-assembly explorer

[Execution Atlas](docs/explorer.md) connects model operators to measured
RISC-V instructions, C++ source, and hot loops. Its **Simulator** tab supports
live stepping, registers, memory, and stage-aware breakpoints.

The optional viewer requires Node.js and npm. For the LiteRT profile produced
by `midterm-benchmark`:

```sh
npm ci --prefix explorer
gmake explorer-export PROFILE_CONFIGURATION=midterm-A0
gmake app-dev PROFILE_CONFIGURATION=midterm-A0
```

Open **http://127.0.0.1:5174/#simulator**. Both Explorer and Simulator use the
matching baseline bundle and ELF. Ctrl+C stops the frontend and backend.
Existing historical LiteRT bundles use `PROFILE_CONFIGURATION=B0`. The
[simulator guide](docs/simulator.md) documents the available controls and
artifact requirements.

## Additional RTL evaluation

The repository also contains [CV-Wally RTL implementations](docs/cvw-verilator.md)
and [recorded full-model simulations](results/cvw/full-x5/README.md) for the
baseline, accepted software, and X1–X5. These results are separate from the
midterm ISA evaluation. Mapped area and physical Fmax are unavailable; the
[synthesis record](results/synthesis/baseline/README.md) documents the DC startup
failure.

The [extended evaluation index](docs/submission.md) links RTL sources,
verification, cycle measurements, and synthesis configuration.
`gmake submission-report` regenerates the combined Spike/RTL reports when the
archived raw evidence is available. `gmake submission-package` creates a
checksummed source/evidence archive under `build/submission/`, excluding
downloaded toolchains and local access settings.
