# Compiler profiling and evidence

Profiling is a gate before accepting an optimization checkpoint. The compiler
configuration comes from the measured build, while the checkpoint is a human
label. `PROFILE_CONFIGURATION=A0` still does **not** select the compiler backend
in the existing LiteRT targets. B0's collector, sources, captures and reports are
preserved.

This work brings profiling forward from compiler Stage 9, before Stage 5 kernel
optimization. It has three separately gated checkpoints:

1. **Foundation:** execution contracts, immutable build snapshots, repeated full
   A0 retirement profiles, offline reports, and B0/parent comparisons.
2. **Kernel investigation:** isolated replay with oracle intermediates, a scalar
   dot-product microbenchmark, and byte-verified GCC diagnostic artifacts.
3. **Viewer:** schema v2 import/export, execution-plan and planned-memory views,
   and browser acceptance. No v1 compatibility is required. Old measurements
   can be re-exported into the new schema when needed.

All three observability checkpoints are implemented for A0 and subsequent B1
builds. The [accepted software-B1 report](B1-software-report.md) records the
selected configuration, repeated profiles and offline comparisons. There is no
browser comparison dashboard or profiling job launcher.

## Reproduce

```sh
# Build and validate the exact compiler ELF, then collect two full profiles.
gmake compiler-a0-profile

# Profile an already built, frozen build record without rebuilding it.
gmake compiler-profile COMPILER_PROFILE_BUILD=build/compiler/A0/rv64/build.json \
  COMPILER_CHECKPOINT=A0-stage4-profile

# Complete correctness + collector + repeated full-profile checkpoint gate.
gmake compiler-checkpoint COMPILER_CHECKPOINT=A0-stage4-profile

# Reconstruct reports from saved evidence only; does not invoke Spike.
gmake compiler-profile-report

# Fast foundation checks; complete collector fixtures have a separate target.
gmake compiler-profile-tests
gmake profile-tests
```

The equivalent CLI is `python tools/profile_compiler.py run --build-manifest
<build.json> --checkpoint <label> [--parent <capture>]`, or `report --capture
<capture> --output <directory>`. A capture can be its immutable directory,
`manifest.json`, or the convenience `latest.json` pointer. Parent comparisons
use an explicit saved capture. Labels never replace or select implementation
code. This first adapter accepts actual RV64 A0 records only; future backends
must supply their own validated build/ISA integration.

## Compile-time evidence

Generation adds `execution_plan.json` with schema version 2. Original graph nodes,
execution units, and runtime events are separate identities. Units record their
logical origins, ordered schedule, actual implementation/backend, operands,
source region, memory/parameter placement and work-count policy. Origins can
reference several units, several origins can share a unit, and an eliminated
origin has no fabricated event. The initial A0 plan maps the 64 existing wrappers.
The view-only Reshape still has a real wrapper whose call/return work is counted.

Before compiling each translation unit, the builder obtains dependencies using
the actual flags. It hashes them, compiles with a dependency file, and verifies
the discovered set and bytes again. It preserves system headers as well as
project/upstream headers. A content-addressed snapshot freezes those bytes,
generator sources, generated artifacts, build commands, flags, compiler identity,
and the ELF. New RV64 snapshots also hash object files, the linker script and
selected static libraries before/after linking, and verify the link-map inputs.
Snapshot identities are distinct from ELF and checkpoint identities.

The build record points to `evidence/<sha256>/manifest.json`. Its content-addressed
blobs are read without consulting their original paths. Historical profiling can
therefore use a saved build after source files or live generated files change.
Snapshots contain full constants/IR for reproducibility; viewer export
omits model-weight payloads by default.

## Runtime evidence and boundaries

The adapter resolves the root and every execution-unit symbol in the actual
linked ELF. It rejects absent/ambiguous symbols or undecodable entries. Shared
function entries have one collector probe; the validated schedule distinguishes
their occurrences. A unit cannot alias the invocation entry.

The existing simulator-side retirement collector is unchanged. Its private
`invoke`/`operator` protocol is adapted into compiler unit identities; there is
no target counter, added marker instruction, or diagnostic callback. The existing
production wrappers and their optimization constraints remain part of the
measured compiler executable.

Invocation includes entry through its returning instruction. The caller call is
excluded; unit scopes include callees and tail callees. Input generation, stack
painting, checking, guards in the outer harness and printing are excluded. The
Softmax domain preflight stays **inside** inference. Standalone B1 reuses its
checked normalization sum instead of repeating the successful summation pass.

The exact saved ELF runs first in ordinary Spike, then twice in profiling Spike.
Each run must pass the target checks and match all 1,000 public output bytes.
Both CSV event streams and PC histograms must be byte-identical. The adapter
validates entry/order/status/completion, raw instruction bits and lengths, known
classification, uint64 counters, and every PC's partition:

```text
full invocation = disjoint inclusive execution units + invocation overhead
```

There is no allocation event for A0. Source lines, inline frames and function
bodies are additional views of the same counts, not extra additive costs.
Function-body attribution is exclusive and preserves an explicit unattributed
bucket. Shared/fused units must not be divided into invented per-node costs.

## Storage, reports and interpretation

Raw captures live under `build/profiling/compiler/<manifest-sha256>/`. They include
the complete build snapshot, input and expected output, oracle identity, frozen
B0 summary/contract, collector sources/identities, commands, logs, and two sets
of CSVs. A capture is published only after both runs validate; `latest.json` is
only a convenience pointer. Reports verify the archived bytes and identities.

Compact `summary.json`, `units.csv` and `README.md` live in
`results/profiling/<checkpoint>/`. An offline report has no need for live model,
source, generated C++, native oracle, or simulator installations. It uses the
RISC-V binutils tools to resolve/disassemble the saved ELF. Metadata identifies
the capture-time adapter and current report generator separately.

Metrics carry a value, unit, scope, and measured/derived/unavailable evidence.
Integers use decimal strings and ratios preserve exact numerator/denominator
pairs. Logical MACs come from graph shapes. Executed products are **derived** from
the declared backend schedule: A0's pinned convolution skips padded taps. Future
backends processing padded products or tails must update this policy. Unknown
work counts remain unavailable. A multiply opcode is not proof of a useful MAC.

Reports include instruction mix, memory instructions per product, MAC/instruction,
custom frequency (zero for A0), inclusive unit contribution, exclusive functions,
ELF code/readonly/writable/BSS bytes and planned activation/scratch/constants.
Comparisons use compatible model/input/invocation semantics and original logical
node identities. Only uniquely measurable single-node regions get node rows;
whole-model comparisons remain available when units split or fuse.

Spike retirements are not CV-Wally cycles, and memory instructions are not cache
misses or DRAM traffic. AOT workspace and LiteRT's total arena have different
accounting. The known all-zero-point input still fails at Softmax and is covered
by correctness diagnostics; the performance workload remains canonical seed 1.
Performance regressions are recorded, not hidden by a minimum-improvement gate.

## Kernel replay and scalar microbenchmark (checkpoint 2)

```sh
# Use existing verified A0 and oracle snapshots. Three build kinds by default.
gmake compiler-replay

# All eight input cases, including residual/alias/error coverage, on both hosts.
uv run --python 3.12 python tools/profile_compiler.py replay \
  --nodes 1,4,8,15,58,61,10,60,62 --cases all --kinds native,sanitized \
  --output-root build/compiler/replay-correctness \
  --results-dir results/profiling/A0-replay-correctness

# GCC diagnostics, followed by the complete checkpoint-2 acceptance workflow.
gmake compiler-gcc-analysis
gmake compiler-investigation-checkpoint
gmake compiler-investigation-tests

# Offline reports accept either an investigation directory, manifest or pointer.
uv run --python 3.12 python tools/profile_compiler.py report \
  --capture build/compiler/replay/latest.json --output results/profiling/A0-replay
uv run --python 3.12 python tools/profile_compiler.py report \
  --capture build/compiler/gcc-analysis/latest.json --output results/profiling/A0-gcc
```

`replay` accepts a frozen RV64 `--build-manifest`, a matching frozen
`--host-build-manifest` (native by default), a verified `--oracle`/`--golden`,
comma-separated `--nodes`, `--cases` (`all` for the complete Stage 0 suite), and
`--kinds native,sanitized,rv64`. Defaults exercise nodes 1, 4, 8, 15, 58 and 61
on the canonical input. Custom experiments should use a separate `--output-root`
and `--results-dir` to preserve the canonical acceptance pointers.

The harness includes the saved generated model unchanged in an investigation
translation unit and adds accessors to its private arena. Every runtime operand
is restored from the correct producer's oracle output (or the public input),
including both residual ADD operands. Weights and prepared parameters remain in
the compiled original constants. The fixture pack is aligned, content-checked,
and deduplicates identical byte arrays. Native platform headers absent from the
RV64 snapshot come from a verified host snapshot of the same generated artifacts;
the replay compiler additionally freezes its actual dependencies.

Before every invocation, the harness resets guards and restores inputs. It
poisons nonaliased outputs with bytes different from the expected result, then
compares the **entire** result after execution. Proven read-only views retain
their aliased inputs. Setup, poisoning, restoration, checks and printing are all
outside `replay_invoke`; its tail-call to the selected unit is measured separately
from that unit's inclusive count. RV64 runs once in ordinary Spike and twice in
the unchanged retirement collector. Every event, return status, byte comparison,
instruction decode and per-PC partition must validate; both captures must match.

There are also two sizes (K=16 and K=320) of one scalar dot-product microbenchmark.
They use real first-pixel/output-channel-zero operands and bias from nodes 4 and
58. Expected raw INT32 accumulators are calculated independently with Python
integers. The measured `replay_dot` wrapper calls the existing `cc_dot` path,
**including its int64 accumulation/overflow checks**. This is not a full quantized
convolution or requantization benchmark.

The zero-point case's node-62 replay expects status 2 and verifies that every
poison byte remains untouched; it has no reference probability output. Its raw
counts are explicitly diagnostic, not a successful performance result. Node 63
cannot be replayed for that input because its reference producer output does not
exist; the request fails before building.

Replay archives have `format: compiler-kernel-replay`, schema version 2, and live
under `build/compiler/replay/`, `replay-correctness/` and `replay-edge/`, each
keyed by its manifest SHA-256.
They preserve the source snapshots, oracle identities, fixture data, generated
harness, build commands/dependencies, binaries, checks and raw histograms.
Replay ELFs have separate identities from production A0. Even when measured unit
counts happen to agree, isolated counts do not replace full-inference profiles.

## Verified GCC investigation (checkpoint 2)

`analyze --build-manifest <build.json>` restores the saved production sources and
headers into a separate workspace. It uses the recorded compiler, optimization,
ISA, ABI and link commands, mapping source prefixes back to the original paths.
Every actual compiler dependency must agree with the frozen build. It selects
all C/C++ executable translation units from the inventory, rather than the
LiteRT four-file whitelist. Constants are rebuilt without giant diagnostic dumps;
startup assembly remains in the command inventory.

For generated model code, reference numerics, common helpers, the target harness
and platform syscalls it collects original tree, initial/optimized GIMPLE, RTL
expansion/final RTL, inlining analysis, emitted assembly, optimization remarks and
pass discovery. Each artifact includes hash-bound function ranges. Preprocessed
header dumps are discarded because source bytes are already preserved.

Analysis is attached only after comparing **every allocated section and loadable
segment**, including addresses and data, with the measured ELF. A changed loaded
byte rejects the attachment. Debug information and compiler dumps keep separate
identities. `compiler_analysis.json` and the content-addressed archive preserve
all correspondence evidence for checkpoint 3. Reports validate archived data
without invoking GCC or consulting live project sources.

Older checkpoint-1 snapshots did not preserve the linker script. For those builds,
investigation can recover the exact pinned script from the verified Stage 0 B0
archive, records this supplemental provenance, and still requires complete loaded
image equality. New production snapshots include linker inputs directly. Pinned
compiler installations are needed to rebuild analysis; saved report validation
does not require them.

## Single-build viewer (checkpoint 3)

```sh
# Validate the saved capture and optional GCC archive, then export a v2 bundle.
gmake compiler-export
# Omit GCC dumps while retaining source, assembly, registers and compiler plans.
gmake compiler-export COMPILER_ANALYSIS= COMPILER_VIEWER_BUNDLE=build/explorer/A0-small.zip
# Select the already exported local asset; the label does not select a backend.
gmake explorer-dev PROFILE_CONFIGURATION=A0
# Regenerate both A0/B0 v2 bundles and run export, frontend and browser gates.
gmake compiler-visibility-checkpoint
```

CLI: `python tools/profile_compiler.py export --capture <capture-or-manifest>
[--compiler-analysis <analysis-or-manifest>] --output <bundle.zip>`. The `run`,
`report`, `replay` and `export` operations all consume verified manifests. Export
uses the measured ELF in the capture and does not rebuild or run inference.
Source bytes are exclusively build snapshots, including after live source changes.
Verified analysis may use a newer snapshot with additional linker dependencies,
but must match the exact measured ELF, generated artifacts and shared dependency
hashes. All allocated bytes/layout and loadable segments are rechecked.

The v2 bundle separates graph-node origins, execution units and measured events.
An inference partition consists of unit events plus invocation overhead; setup is
optional and separate. Node views union their unit events without duplicate counts.
Fused costs remain shared, split units are aggregated, and eliminated/unobserved
nodes display **Unavailable**, never a synthetic zero-cost event. Browser sums are
exact integers. No per-node allocation of fused costs is inferred.

The compiler inspector shows implementation/backend identities, operands, notes,
source regions, prepared parameters, memory contracts and supporting artifacts.
The memory plot displays physical offsets and inclusive lifetimes in **execution
steps**, with separate activation, scratch, read-only and unavailable-stack
accounting. Aliases expose both logical tensor lifetimes and physical-group union
lifetimes. Build metrics retain explicit scope, unit and evidence categories.
DWARF locations, conservative GCC correspondences and measured PC counts retain
separate provenance; the viewer does not claim sampled register values.

Only one bundle is open at a time. Offline report comparisons remain outside the
viewer. Schema v1 imports are intentionally unsupported: regenerate B0 bundles
with `gmake explorer-export`. Raw B0 captures and frozen artifacts are unchanged.
Default bundles omit ELF payloads, model buffers, fixture blobs and generated
`constants.cc`; the saved build inventory still lists their reproducibility hashes.
Archive integrity, file/entry limits, references and per-PC conservation are checked
in the import worker. See [explorer.md](explorer.md) for navigation and limitations.

## Design references

The separation of compile-time provenance and runtime events follows
[ExecuTorch's developer tools](https://docs.pytorch.org/executorch/stable/devtools-overview.html).
Separate full inference and replay follow the investigation model described by
[IREE](https://iree.dev/developers/performance/profiling/). Optimized source mapping
and later compiler evidence use the pinned toolchain's
[GCC debug information](https://gcc.gnu.org/onlinedocs/gcc-15.2.0/gcc/Debugging-Options.html)
and [diagnostic outputs](https://gcc.gnu.org/onlinedocs/gcc-15.2.0/gcc/Developer-Options.html).
[Spike](https://github.com/riscv-software-src/riscv-isa-sim) supplies functional ISA
execution; hardware timing remains a separate workstream.
