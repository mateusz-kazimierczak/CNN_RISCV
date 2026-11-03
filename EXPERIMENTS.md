# Experiment and evidence index

The midterm evaluates full-model ISA-level work in Spike. The
[midterm results](results/midterm/README.md) contain the main checkpoint comparison;
the [evaluation guide](docs/midterm-submission.md) defines the workload, commands,
verification, and measurement boundaries.

## Midterm evaluation

After the [host setup](README.md#build-and-run), run the baseline, instruction
tests, and full benchmark sequentially:

```sh
gmake run-native
gmake run-spike
gmake midterm-tests
gmake midterm-benchmark
```

| Evaluation | Command | Evidence |
|---|---|---|
| Bare-metal LiteRT correctness | `gmake run-native`, then `gmake run-spike` | Reference output/checksum in the [README](README.md#build-and-run) |
| Short custom-instruction verification | `gmake midterm-tests` | [ISA coverage](docs/midterm-submission.md#expected-results-and-verification) |
| Fresh LiteRT full-model profile | `gmake midterm-baseline` | `results/profiling/midterm-A0/`; [frozen reference](results/profiling/B0/README.md) |
| Complete software/custom-ISA benchmark | `gmake midterm-benchmark` | [Midterm results](results/midterm/README.md) |
| Retained-evidence report regeneration | `gmake midterm-report` | [Comparison CSV](results/midterm/progression.csv), [validation record](results/midterm/validation.json) |

The midterm targets use Spike without RTL snapshots or synthesis tools.
Report regeneration requires the raw captures and build evidence produced by the
benchmark. The compact results are included in the repository.

The main progression is **A0 → B1.1 → B1.2 → B1.3 → B1.5 → B1.6 → B1.7 → X1 → X2 → X3 → X4 → X5**.
B1.4 stem unrolling is grouped into B1.5. X1.1–X1.4 and X2.1–X2.3 record ISA
introduction and compiler refinements; D1 isolates software zero-point correction
before X4. X3.broad is an alternative from X2. X5 adds no new ISA.

## Individual checkpoint workflows

The [software manifest](experiments/software.json) and
[ISA manifest](experiments/hardware.json) specify cumulative options and
comparison parents. Their [software](experiments/README.md) and
[ISA](experiments/hardware.md) guides describe capture selection and validation.

| Comparison | Reproduce | Evidence |
|---|---|---|
| B1.1 custom compiler → B1.7 | `gmake software-experiments` | [Software results](results/profiling/B1-reordered/README.md) |
| Accepted software B1 | `gmake compiler-b1-software-checkpoint` | [Selection](results/profiling/B1-software/selection.json), [development history](docs/B1-software-history.md) |
| Packed MAC with selected 2×4 schedule | `gmake compiler-x1-tile2x4-checkpoint` | [X1](results/profiling/X1-tile2x4/README.md) |
| Requantization and scheduling | `gmake compiler-x2-optimized-checkpoint` | [X2](results/profiling/X2-optimized/README.md) |
| Selected post-increment | `gmake compiler-x3-checkpoint` | [X3](results/profiling/X3-selected/README.md) |
| Software depthwise control and bank ISA | `gmake compiler-x4-checkpoint` | [D1](results/profiling/D1/README.md), [X4](results/profiling/X4/README.md) |
| Packed RGB stem | `gmake compiler-x5-checkpoint` | [X5](results/profiling/X5/README.md) |

Historical target/folder names remain in the implementation. Main X1 is
`X1-tile2x4`; folder `X1` is X1.1. Main X2 is `X2-optimized`; folder `X2` is
X2.1. X2.2 is `X2-submission-02-outline`. D1 → X4 isolates the bank ISA effect;
main X3 → X4 includes the D1 software improvement.

Whole-stage gains include their recorded software schedules. X1's selected 2×4
packed schedule differs from B1.7's scalar 2×2 schedule. Node-level comparisons
and manifests retain these distinctions; the whole-stage gains do not isolate
an opcode's benefit from compiler tuning.

## Additional RTL and synthesis evaluation

| Evaluation | Command or workflow | Evidence |
|---|---|---|
| Accepted ISA stages with archived RTL cycles | `gmake hardware-experiments` | [Hardware progression](results/profiling/hardware-progression/README.md) |
| Combined Spike/RTL report | `gmake submission-report` | [Combined results](results/submission/README.md) |
| Fresh hardware-era Spike captures | `gmake hardware-recapture` | Separate `HW-*` builds and captures |
| CV-Wally directed/replay evaluation | `gmake cvw-xqmac8-checkpoint` and corresponding extension targets | [RTL implementation guides](DESIGN.md), `results/cvw/` |
| Hardware-cost evaluation | Platform-specific synthesis workflow | [Synthesis setup](synth/README.md), [measurement status](results/synthesis/baseline/README.md) |

Combined-report validation uses archived RTL snapshots. RTL execution and
collection use the pinned Linux/WSL workflow and exact workload contracts.
D1 has no separate full-model cycle measurement. Physical area and Fmax are
unavailable, as documented in the synthesis record.

`gmake submission-package` creates a source/evidence archive and checksum under
`build/submission/`, including selected immutable captures and RTL snapshots.
The [extended evaluation index](docs/submission.md) maps those artifacts and
measurement scopes.
