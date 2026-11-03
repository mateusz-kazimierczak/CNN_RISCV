# Architecture and implementation map

The workload is frozen W8A8 EfficientNet-Lite0: 64 operators, approximately
385 million logical MACs, UINT8 public input/output and INT8 internal activations.
The target is bare-metal RV64IMC. The implementation distinguishes ordinary
software optimization from ISA work and CV-Wally hardware performance.

| Component | Design and source |
|---|---|
| LiteRT Micro baseline A0 (historical B0) | [Runtime](tflm/README.md), [platform](tflm/platform/rv64imc/README.md), [model provenance](models/README.md) |
| SALT custom compiler B1.1 (config A0) | [Compiler](docs/compiler.md), `compiler/`, `kernels/reference/` |
| Cumulative optimized software B1 | [Software report](docs/B1-software-report.md), [experiment manifest](experiments/software.json), `kernels/project/`, `kernels/rv64imc/` |
| Grouped custom-ISA progression | [Hardware-era report](docs/hardware-optimization-report.md), [manifest](experiments/hardware.json), [ISA measurements](results/midterm/README.md) |
| Packed MAC Xqmac8 | [ISA/compiler](docs/xqmac8.md), [RTL](docs/cvw-xqmac8.md) |
| Exact requantization Xrequant | [ISA/compiler](docs/xrequant.md), [scheduling](docs/xrequant-optimization.md), [RTL](docs/cvw-xrequant.md) |
| Post-increment Xpostinc | [ISA/compiler](docs/xpostinc.md), [RTL](docs/cvw-xpostinc.md) |
| Eight-lane depthwise Xdwmac8 | [ISA/compiler](docs/xdwmac8.md), [RTL](docs/cvw-xdwmac8.md) |
| Packed RGB stem | [Software schedule using Xqmac8](docs/stem.md) |
| Measurement and provenance | [B0 contract](docs/profiling.md), [compiler contract](docs/compiler-profiling.md) |

Spike establishes retired instruction counts, instruction mix and exact outputs.
It does not establish hardware cycles, CPI, cache misses, area or Fmax. RTL and
synthesis evidence have separate directories and configurations. Per-node joins
use logical graph identity, never linked addresses.
The preserved [full-model RTL results](results/cvw/full-x5/README.md) cover A0 (stored as B0),
accepted B1 and X1–X5. The [synthesis status](results/synthesis/baseline/README.md)
records the DC startup failure; mapped area and physical Fmax are unavailable.

SALT prepares the graph, integer parameters and static memory offline. B1.1 keeps
reference kernels; B1.2–B1.7 progressively specialize arithmetic and traversal until
the target is independent of TFLM kernel headers. LiteRT remains the frozen
model source and oracle. No custom instruction is used in the B1 sequence.

The accepted B1 and historical experiment lineage are preserved. The
configuration manifests in `experiments/software.json` and
`experiments/hardware.json` specify code-generation options and comparison
parents. Capture identities and build hashes bind measurements to the executed
programs.
