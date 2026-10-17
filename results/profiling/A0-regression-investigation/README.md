# A0 instruction regression investigation

The original A0 regression is real, but it is not the cost of removing the
interpreter. Its generated C++ hides static facts from GCC and produces worse
convolution loops. Two independent shape-construction ablations reverse the
regression without changing any reference kernel algorithm.

## Full-inference measurements

| Build | Retired instructions | Change from B0 |
|---|---:|---:|
| Frozen B0 | 4,867,278,370 | baseline |
| Original A0 | 6,063,975,187 | +24.59% |
| enable-builtins | 4,176,787,289 | -14.19% |
| explicit-shapes | 4,176,397,081 | -14.19% |
| explicit-shapes-and-scalars | 3,980,184,493 | -18.23% |

Each experimental ELF passed ordinary Spike and two profiling Spike runs.
Both event files and every PC histogram were byte-identical between repeats;
all 64 units reconciled with the invocation and all 1,000 public output bytes
matched the canonical seed-1 oracle. Experimental counts have the same invocation
boundary as B0/A0. These are retirement-count changes, not cycle measurements.

## What caused the regression

1. **Static shapes are obscured by an opaque copy.** `emit_cpp.py` constructs
   `RuntimeShape(rank, dims_N)`. The pinned constructor calls `std::memcpy`, while
   the RV64 build passes `-fno-builtin`. The saved optimized GIMPLE still contains
   four `memcpy` calls in node 4, loads of runtime dimension members, and divisions
   for groups and filters per group. A known 1x1 convolution remains a general
   convolution nest. The cost of the copies themselves is small; the important
   cost is the specialization that cannot happen afterward.

2. **The resulting hot loop spills registers.** Node 4's measured A0 reduction
   executes 12 instructions per product, including a stack store/reload of the
   filter value and reloads of the input zero point and loop endpoint. Those four
   stack accesses retire 77,070,336 times collectively. Its B0 counterpart uses
   eight instructions. All A0 SP-addressed memory operations total 1,743,045,971,
   versus 235,949,991 in the B0 invocation (an addressing subset, not a complete
   stack-traffic classification). This is executed instruction overhead, not a
   claim about cache behavior or stalls.

3. **Prepared scalars are stored as data, not exposed as compiler constants.**
   `constants.h` declares an external aggregate; its values are defined in
   `constants.cc`. Separate compilation without LTO leaves padding, zero points,
   activation limits and other scalar fields unknown while compiling `model.cc`.
   The shape-only optimized node 4 still tests padding at runtime. Emitting those
   same scalar values as literals removes those tests and more live values.
   Per-channel arrays and weights remain compiled constants in every experiment.

4. **A0 currently selects reference calls, not specialized B1 loops.** This is
   explicit in `lowering.py` and the Stage 4 guidelines. Removing dispatch saves
   very little here: B0's interpreter overhead is only 4,820 instructions
   (0.000099% of inference). It does not remove the dominant multiply, load,
   quantization or loop work. The static compiler must deliberately expose its
   knowledge and select better loops to deliver those savings.

## Controlled changes

All variants were linked from the same frozen inputs, weights, prepared arrays,
reference kernels and remaining object files. The frozen inputs were first rebuilt
and verified to have identical allocated sections and load segments to original
A0. ISA, ABI and `-O2` stayed fixed. Only the generated model object changed.

- **enable-builtins:** unchanged generated source; omit `-fno-builtin` for this
  object. Node 4 becomes an eight-instruction reduction with no stack accesses
  inside that reduction. It falls from 398,850,865 to 249,513,182 instructions.
- **explicit-shapes:** retain `-fno-builtin`; replace only shape construction by
  `RuntimeShape(rank)` followed by explicit `SetDim` assignments. Its similar full
  result isolates shape visibility as the main cause, rather than requiring a
  broad build-flag change.
- **explicit-shapes-and-scalars:** keep the shape change and substitute literal
  values for prepared scalar element accesses. Node 4 falls to 228,990,399;
  node 58 falls from 249,752,376 to 164,703,520. This tests constant visibility,
  without adding packed arithmetic, unrolling, fused nodes, or a new kernel.

These ablations prove the end-to-end effect of the representation choices and
the resulting GCC output. They do not identify a unique register-allocation
heuristic responsible for each spill. Builtin recognition and explicit shape
assignment also affect other reference operators; the full reduction must not be
attributed solely to node 4 or to removed `memcpy` call instructions.

## Where the original increase occurred

1x1 convolution adds **1,335,909,524** instructions, more than the entire net
regression. Depthwise 3x3 saves 79,008,495 and depthwise 5x5 saves 98,037,089;
stem convolution adds 34,862,906. The full grouped and per-node accounting is in
[summary.json](summary.json) and [units.csv](units.csv).

## Recommended next implementation

Preserve A0 as measured. In the next software optimization checkpoint, expose
shape and scalar metadata explicitly in generated C++, retain reference fallback
and numerical helpers, then add the planned scalar 1x1 kernel specialization.
Measure the metadata change separately before changing loop algorithms. Prefer
explicit shape initialization over globally enabling builtins: the controlled
test shows that this fixes the main issue while retaining the bare-metal flags.
Inspect assembly for constant loop limits, eliminated general padding/group work,
and spills; source-level constants alone are not an acceptance criterion.

The diagnostic variants have seed-1 full-output evidence only. They still need
the existing multi-input, every-node, sanitizer and replay correctness gates
before promotion. No production compiler, kernel, build flags or frozen B0
artifact was changed by this investigation. All 40 frozen B0 hashes and the
production A0 ELF hash were checked unchanged.

## Reproducibility

Immutable artifact: `build/compiler/regression-captures/de41428f05200039dc4f591cd91e6b30700e56b90b5e7a4fc12f0dd5fe180be6/`.
Its manifest content identity is `de41428f05200039dc4f591cd91e6b30700e56b90b5e7a4fc12f0dd5fe180be6`. The archive preserves the
frozen build evidence, rebuilt workspace, variant sources/ELFs, exact commands,
optimized GCC trees, ordinary execution outputs, repeated event/PC captures and
the scripts used for these experiments. Recorded commands refer to the original
work directory recorded in the manifest; restore that directory when replaying.

Production A0 ELF: `ad7135f142507b3e727e61bca4b0e8dc27eff8c4e6df5c6e85aa940b103f604e`.
Input and output are the original canonical seed-1 fixtures. No model weights
are copied into this compact results directory.
