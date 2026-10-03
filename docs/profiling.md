# Spike instruction profiling

This workflow establishes **B0**, the existing EfficientNet-Lite0 TFLM reference
kernel build on RV64IMC. It changes neither the model nor its target instructions.
It characterizes instruction work, not CPU timing.

## Run and navigate

From the repository root, after the ordinary native/Spike setup:

```sh
gmake profile-tests
gmake profile-spike
gmake profile-report
```

`profile-spike` builds a separate debug ELF, checks its loaded sections and
segments against the ordinary ELF, runs ordinary Spike for correctness, and
captures **two** full profiling runs. Both profiles must agree exactly and all
three runs must produce the native reference output. It also runs directed tests.
`profile-report` uses Python's standard library and saved captures only; it does
not run Spike or read the FlatBuffer. Capture uses `uv` for `tflite` and `numpy`.

Read the [B0 summary](../results/profiling/B0/README.md) and
[reviewed analysis](../results/profiling/B0/analysis.md). `summary.json` holds
provenance, metrics, shapes, per-layer counts, and hotspots; `layers.csv` has one
row per node. These compact results belong in Git. Raw histograms, logs, the
report-input manifest, and debug ELF stay in ignored `build/`; simulator trees
stay in ignored `.deps/`. No full-model instruction trace is produced.

## Measurement boundaries

Inference begins at `MicroInterpreter::Invoke()` entry and ends on the
instruction returning to its saved caller address. The caller's call is outside;
the return is inside. This works with `Invoke()`'s tail call to `InvokeSubgraph()`.
Allocation is a separate `AllocateTensors()` region, including preparation and
software FP scale calculations; it is not all application startup. Input filling,
output checking, and printing are outside inference.

Operator callback histograms include their callees and tail callees. The fixed
graph has one subgraph and 64 sequential nodes; callback order identifies node
indices, and the analyzer validates every type against the FlatBuffer. Dispatch
and temporary-allocation cleanup are outside callbacks but inside inference:

```text
Invoke instructions = sum(64 callback totals) + interpreter overhead
```

Entry is observed before execution, including instructions that trap or request
serialization. Counts increment only at retirement, before timing-after triggers.
`PC_SERIALIZE_BEFORE` counts nothing; `PC_SERIALIZE_AFTER` counts once. The stock
global histogram's execution hook is not used. Counters are 64-bit.

Traps inside regions invalidate the capture even if a handler returns. Missing
returns, nonzero return status, nested region/callback entry, unexpected graph
order, unknown classification, and inconsistent sums are rejected. The collector
supports one hart and rejects self-modifying instructions and execution outside
the configured code range while measuring.

## Collector interface

The tracked `tools/spike_profile/spike.patch` includes `roi_profiler.h` in the
pinned Spike processor. The build helper applies it to an isolated clone, checks
for unexpected dependency changes, and rebuilds when the patch/header changes.
The ordinary simulator installation is untouched.

Use `--profile-config=<file>` and `--profile-output=<prefix>` together. The host
generates whitespace-delimited records with ELF-derived addresses:

```text
code <text_start> <text_end>
region allocate <entry_address>
region invoke <entry_address>
operator CONV_2D <entry_address>
```

The actual configuration includes all eight callbacks. `<prefix>.events.csv`
records event identity, boundaries, completion, status, and totals;
`<prefix>.pcs.csv` records event, PC, raw instruction bits, length, and count.
Dense halfword-indexed counter arrays avoid per-instruction hash lookups.

## Interpret the results carefully

- Compressed and full-length instructions each retire once. GNU objdump decodes
  without aliases, and every executed mnemonic has an explicit classification.
  Division/remainder and jumps have separate bins.
- Logical MACs include padded convolution positions. Executed products count
  only valid positions, following the reference kernels' skip-padding behavior.
  Neither count includes bias, scaling, or elementwise work.
- Loads plus stores are dynamic memory instructions, not instruction fetches,
  cache misses, DRAM transactions, or memory bandwidth.
- Fixed-point scaling counts cover both `MultiplyByQuantizedMultiplier` helper
  bodies. Caller calls, zero-point addition, clamps, and stores are excluded.
  This is not all requantization; ADD also performs input scaling, which can be
  inlined and absent from the out-of-line helper count.
- Function counts are exclusive PC attribution; layer counts are inclusive.
  Inline DWARF frames are retained, but optimized source-line mappings do not
  uniquely separate arithmetic from address calculations. Inspect disassembly.
  A multiply instruction is not necessarily a MAC.
- Executable size excludes model/data and non-loadable debug sections. BSS
  includes the reserved arena, not just the used arena.
- Spike models `mcycle` at CPI=1. Host wall time measures simulator throughput.
  Neither represents CV-Wally cycles, stalls, or timing speedup.

## Reproduction and subsequent configurations

Reports record repository revision and dirty status, compiler and resolved flags,
TFLM/Spike revisions, model/ELF/patch/header/collector/analysis hashes, seed,
checksum, boundaries, and repeat agreement. A report made before a commit
honestly records a dirty tree; hashes identify its actual measured artifacts.

Keep B0 unchanged when introducing B1 software optimization and X1/X2 custom
instructions. Preserve each configuration's captures/results separately, keep
inputs and boundaries fixed, and repeat all correctness and collector checks.
The runner accepts `--configuration B1` (or X1/X2) to select separate directories;
this labels outputs, not a different kernel or ISA. The extension milestone must
also expose its simulator ISA flags and supply matching ordinary/debug ELFs.
Update callback-symbol attribution and explicitly classify new custom encodings
when implementing extensions; unknown instructions must never silently become
ALU instructions. If kernels process padded products later, update executed-work
accounting rather than reusing the B0 skip-padding count.

Standalone kernel extraction is the next milestone, using the measured layer
shapes. Cache behavior, stalls, CPI, area, and timing require explicitly configured
microarchitectural/RTL evaluation; they are not conclusions of this profile.

## Validation

Directed bare-metal programs have hand-counted regions, checked against stock
Spike's commit log. They cover compressed instructions, loads/stores, arithmetic,
multiply/divide, branches, nested calls, tail returns, serialization, traps, and
incomplete captures. Host tests cover >32-bit counts, 64-bit overflow, padding
formulas, and unknown/forbidden classifications. CSR fixtures use test-only
`rv64imc_zicsr`; the model remains `rv64imc`. Full-model acceptance additionally
requires identical loadable bytes, exact graph order, reconciled sums, two equal
histograms, and the native reference output.
