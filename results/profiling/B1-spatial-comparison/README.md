# B1 spatial pointwise blocking

The accepted configuration uses **2x2 tiles for all 32 pointwise layers** with the
parent's exact scaling policies. Full inference retires **1,576,585,275
instructions**, saving **73,440,496 (4.451%)** against the requantization checkpoint.
Memory instructions fall by **80,492,219 (14.386%)**, and executable code shrinks
**2,052 bytes**, from 54,520 to 52,468. The observed canonical-input stack watermark
remains **584 bytes**. All 32 pointwise units improve; the other 32 unit counts
are unchanged. Two full event/PC captures match byte-for-byte, with every PC
reconciled and all 1,000 public output bytes compared.

These are software-only RV64IMC instruction counts under the same pinned GCC
`-O2` build. Spike retirements are not hardware cycles. Compared with B0 the
accepted build retires 67.608% fewer instructions; compared with corrected A0,
60.389% fewer.

## Measured alternatives

| Configuration | Full retirements | Fewer vs parent | Memory instructions | Executable bytes |
|---|---:|---:|---:|---:|
| Parent B1 | 1,650,025,771 | +0.000% | 559,509,746 | 54,520 |
| 2x4, parent scaling | 1,775,982,033 | -7.634% | 698,387,068 | 71,092 |
| 2x4, shared pointwise scaling | 1,797,765,968 | -8.954% | 699,667,059 | 68,764 |
| 2x2, parent scaling (accepted) | 1,576,585,275 | +4.451% | 479,017,527 | 52,468 |
| 2x2, shared pointwise scaling | 1,598,070,860 | +3.149% | 479,159,338 | 51,388 |

All four experiments use their ordinary optimized RV64 ELF and two identical
full captures with exact canonical-output validation. The accepted experiment
additionally passes full native/capture/sanitizer differential and isolated-replay
gates. The shared-scaling alternatives retain the parent's stem/depthwise
choices and use the out-of-line nonpositive-shift helper for every pointwise
unit. None improves on the 2x2 experiment with the original scaling choices.
No performance threshold hides regressions: both 2x4 experiments are slower in
retired instructions and remain explicitly named alternatives.

The control build with spatial blocking disabled has **identical allocated
sections and load segments** to the parent. Its separate ELF identity reflects
debug/source evidence; no new control capture or invented measurement is needed.
[Control identities](control.json).

## Why 2x2 wins

The old one-pixel OC4 schedule reuses each activation across four output channels
but reloads each weight for every pixel. The new 2x2 schedule loads two activations
and two weights for four products, sharing each weight across two pixels and
using four independent accumulators. At the reduction-source level this changes
the nominal load count from 1.25 to 1 load per product; complete measured costs
include parameter loads, stores, tails, scaling, spills and wrapper overhead.

The 2x4 version offers more source-level reuse but maintains eight accumulators
with eight input-channel lanes unrolled. The linked GCC output contains heavy
SP-relative loads/stores inside the reduction. Across full inference, direct
SP-relative memory operations rise from **23,242,865** in the parent to
**336,195,323** in the parent-scaling 2x4 experiment. In node 58, individual such
instructions retire 307,200 times, far beyond a function prologue/epilogue.
The result is 138,877,322 additional memory instructions overall.

The accepted 2x2 schedule also increases direct SP-relative traffic to
**32,191,414**, but its other memory accesses fall sufficiently to reduce the
full memory count by 80,492,219. This is a measured register-pressure trade-off
for these kernels and this toolchain; it does not rule out a different 2x4
schedule or a future packed backend. [SP operand counts and attribution scope](stack-accesses.json).

| Logical pointwise node | Parent | Accepted 2x2 | Fewer instructions |
|---|---:|---:|---:|
| 3 | 27,007,272 | 25,897,143 | 4.11% |
| 4 | 97,978,634 | 94,108,830 | 3.95% |
| 7 | 47,873,076 | 46,857,030 | 2.12% |
| 11 | 47,854,161 | 46,838,117 | 2.12% |
| 34 | 49,986,508 | 46,436,670 | 7.10% |
| 57 | 61,446,723 | 56,670,211 | 7.77% |
| 58 | 69,066,916 | 64,647,249 | 6.40% |

## Implementation and evidence contract

`ScalarDot8SpatialBlock` separates the two-pixel schedule from its eight-lane
scalar reduction. The kernel initializes both pixels from the same corrected
biases, visits input channels in the original order, then rounds/clamps each
output independently. The input zero point remains folded into the existing
prepared biases. No quantization approximation, new products, weight repacking,
packed loads, custom instruction or extra arena scratch is introduced.

Odd pixel counts use the existing one-pixel kernel for the final pixel, with the
same channel block and scaling policy. The loop never forms or reads a fictitious
second input pixel. This covers the model's 7x7 layers and the directed one-pixel
case. Flattening batch/height/width is valid for the proven unpadded stride-one
1x1 geometry. INT32 prefix proofs are reused, and flattened offsets are statically
bounded before C++ indexing.

The compiler has one implementation table for 1x1, 1x2, 1x4, 2x2 and 2x4 tiles.
`--pointwise-pixels` and `--pointwise-block` set defaults;
`--pointwise-tile NODE:PIXELS:CHANNELS` records explicit logical-node overrides.
The same identities drive corrected-bias allocation, source generation, work
counts, execution metadata and viewer navigation. Unsupported geometries or
channel divisibility retain the documented original fallback. Invalid schedules,
duplicate CLI nodes, unsupported override targets, forged plans and conflicting
saved-plan options are rejected. The prior default implementations remain intact.

The selected plan preserves every parent's scaling backend. Prepared IR,
`constants.h` and `constants.cc` are byte-identical to the parent. Tensor and
parameter placements, aliasing, lifetimes, the 1,505,280-byte arena, 4,915,488-byte
planned constants/parameters, 4,915,984-byte allocated read-only storage and
1,505,424-byte BSS are unchanged. Plan hashes change to describe the new kernel
contracts. Useful executed products remain **381,239,488** and logical graph MACs
**385,187,552**; neither is inferred from multiply opcodes.

Memory instructions/product improve from **1.467607 to 1.256474**, and useful
products/instruction from **0.231051 to 0.241813**. Total multiply opcodes remain
389,024,323. Integer ALU instructions rise by 6,994,989; conditional branches by
56,670; jumps by 64. Reduced memory traffic accounts for the net retirement gain.

## Correctness and visibility

**All gates PASS:** 205 compiler tests, five collector tests, eight real B1 browser
scenarios, repeated full profiles, full oracle comparisons, replay and verified
GCC diagnostics. [Artifact-bound verification record](verification.json).

The spatial kernel's independent pinned-kernel tests run under ASan/UBSan:
**240 fixtures, 1,500 kernel calls, 500,100 complete output bytes**. They cover
1/2/3/4/49 pixels, multiple batches, both channel blocks, all numerical policies,
positive/negative generic shifts, nonpositive policy limits, asymmetric zero
points, extreme activations/weights, directed clamps, output guards and random
values. The known-model range and eligibility proofs remain required.

The accepted native release, capture and sanitizer builds match all eight oracle
cases; each capture/sanitizer build compares **510 complete intermediate arrays**.
The known all-131 input retains its status-2 Softmax failure and 62-node prefix.
It is diagnostic evidence, never a successful performance result. Ordinary RV64
verification compares all 1,000 public bytes. Full inference remains the invoke
entry-through-return scope, excluding preparation, painting, verification and
printing; allocation is absent. The 64 unit totals plus 84 overhead instructions
conserve full inference at every PC.

Replay covers nodes 1, 4, 8, 15, 58, 61 and 62 on all eight cases, plus two checked
scalar-dot fixtures: **58 fixtures per native/sanitized/RV64 executable**. Complete
outputs, restored inputs, guards, the odd tail, the diagnostic failure and repeated
RV64 captures pass. Isolated counts and replay ELF identities remain separate
from production. GCC diagnostics cover five executable translation units with
identical loadable bytes before attachment. The v2 viewer bundle exposes the
spatial schedule, retained scaling choices, tail policy, source and actual counts.

The frozen B0 archive verifies unchanged. Refreshed A0 native/capture/sanitized and
ordinary RV64 correctness gates pass, retaining production ELF
`38f37d21f5a6ad833e7b86f53a2cf7f811fa138603e2d7b40312630cb5583fce`.

## Reproduction and identities

The requantization checkpoint was committed and pushed as **`67c7d02`** before
this optimization. The new spatial changes and results remain uncommitted.

- **B1-requantization-selected**: capture `36c3ac40b6ebb1bb8985b0c6990e88b48def27f0ce5af60faa0a6099aca2d291`; ELF `2bd4ec9083ea15912fb2accafd926876d237088aacb231250990f3803c41ac1a`.
- **B1-spatial2-oc4**: capture `2f7e130274edffa7d5b1b7cf93bd82e4985f8ed34b7458e03f78247257cc9a6e`; ELF `61c8a264db2f8649c49ef72b22497dcb075eff7bbcfb7888452071bb79c49908`.
- **B1-spatial2-oc4-shared**: capture `4490aa016e632763d8c71125e918c4ecaf8f41316a8b12403b170219f4681e5e`; ELF `e0ceb29dba008215f5f64b8bbe10bcfa489cdd06f079a2a0a86d7288c296dffc`.
- **B1-spatial2-oc2**: capture `b7e50120ac92412db58bed2d0ccf321a66cc4f44612e366913101bcfd3d0524c`; ELF `d9f1f72d52c386f39edb5f4b331c5d6b0351f26f18dfa50daa0d1e6fcc5914d9`.
- **B1-spatial2-oc2-shared**: capture `5091b2deec835bc4538b0a05d0d2ef2f93d73318a5e4031d3052342e6d1a2cda`; ELF `ec0ea1c39df7e56cde2245f9f3d5f5026b410995d08bc076862ff249c8758544`.

Accepted GCC artifact: `ccfb988759bc34900922dc93bc3e2893f66530568d7a1cbc6c75886e5863bb0a`. Replay artifact:
`72dc4663749b936f3964d7e11f42f439e479a487046e0709281c388ab5ea6c00`; fixture pack `ddd3121cb9516d7dd9ebc7520958d51cf9c2d2b23f42e2e131e9b0a60a9455fa`.
Viewer bundle: `build/explorer/B1-spatial2-oc2.zip`.
Immutable captures, saved build sources/ELFs, GCC dumps and replay evidence remain
in ignored `build/` storage; compact results identify these artifacts.

```sh
gmake compiler-b1-spatial-checkpoint
# Explicit alternatives:
gmake compiler-b1-spatial2-oc4-checkpoint
gmake compiler-b1-spatial2-oc2-shared-checkpoint
gmake compiler-b1-spatial2-oc4-shared-checkpoint
uv run --python 3.12 python tools/profile_compiler.py replay \
  --build-manifest build/compiler/B1-spatial2-oc2/rv64/build.json \
  --host-build-manifest build/compiler/B1-spatial2-oc2/native/build.json \
  --nodes 1,4,8,15,58,61,62 --cases all --kinds native,sanitized,rv64 \
  --output-root build/compiler/B1-spatial2-oc2-replay \
  --results-dir results/profiling/B1-spatial2-oc2-replay
uv run --python 3.12 python tools/profile_compiler.py analyze \
  --build-manifest build/compiler/B1-spatial2-oc2/rv64/build.json \
  --output-root build/compiler/B1-spatial2-oc2-gcc \
  --results-dir results/profiling/B1-spatial2-oc2-gcc
uv run --python 3.12 --with pyelftools==0.32 python tools/profile_compiler.py export \
  --capture build/profiling/compiler/b7e50120ac92412db58bed2d0ccf321a66cc4f44612e366913101bcfd3d0524c \
  --compiler-analysis build/compiler/B1-spatial2-oc2-gcc/latest.json \
  --output build/explorer/B1-spatial2-oc2.zip
```

Regeneration produces fresh evidence identities; use its emitted capture ID.
`B1_SPATIAL_PARENT_CAPTURE`, `B1_SPATIAL_INLINE_NODES` and
`B1_SPATIAL_SHARED_INLINE_NODES` keep comparison parents and scaling choices
explicit. Further optimization and Xqmac integration require new full profiles.
