# Stem convolution: why static specialization regressed

The current stem retires **277,049,718 instructions**, versus B0's
**246,585,264 (+12.35%)**. The static compiler exposes a more expensive GCC
addressing/loop choice for this short reduction. This is avoidable code-generation
overhead; the convolution still executes the same 10,773,600 valid products.

## Exact measured accounting

B0's three-channel reduction uses two advancing pointers and **8 instructions
per product**. Current A0 uses an integer channel index and **19 instructions**.
The hot A0 loop executes two stack reloads and reconstructs the arena and constant
base addresses using four `auipc`/`addi` instructions per product, in addition to
multiple address additions. These are retired instructions, not cache effects.

| Disjoint scope | B0 | Current A0 | A0 minus B0 |
|---|---:|---:|---:|
| Inner reduction PCs | 86,188,800 | 204,698,400 | +118,509,600 |
| All other stem work, including callees | 160,396,464 | 72,351,318 | −88,045,146 |
| Complete stem | 246,585,264 | 277,049,718 | +30,464,454 |

Static information therefore helps substantially outside the reduction. The
worse hot loop more than consumes those savings.

## GCC evidence

The saved GCC induction-variable dump knows that the inner loop has **three
iterations**. It considers separate advancing input/weight pointer candidates,
but chooses one unsigned-long index for both accesses under its estimated cost.
The optimized GIMPLE forms `&arena + offset + index` and
`&a0_constants + offset + index` in the loop. Final RTL/assembly reveals the
stack reloads and repeated global-address materialization.

This is evidence of an unfortunate combination of loop representation and later
register/address lowering. Disabling induction-variable optimization alone barely
helps, so the result should not be explained as a single bad flag or a uniquely
identified register-allocation heuristic. Cost estimates are not measurements of
the final dynamic instruction stream; GCC does not guarantee that specializing
its input produces monotonically better code.

## Controlled isolated experiments

All cases use the same pinned numerical reference path, weights, prepared
parameters and verified canonical stem fixture. Each passes ordinary Spike,
complete output comparison, two identical event/PC captures and ISA decoding.
Only the stem changes. The generic-call control adds a noinline/noipa copy of
the reference function; it is not byte-identical to B0's compiled implementation.

| Diagnostic variant | Stem instructions | Versus B0 | Wrapper bytes |
|---|---:|---:|---:|
| baseline | 277,049,718 | +12.35% | 396 |
| no-ivopts | 276,981,302 | +12.33% | 410 |
| O3 | 126,483,738 | -48.71% | 580 |
| unroll-loops | 126,483,738 | -48.71% | 646 |
| explicit-unroll3 | 146,068,343 | -40.76% | 398 |
| generic-call | 250,615,095 | +1.63% | 188 |
| opaque-input | 236,718,615 | -4.00% | 378 |
| opaque-weights | 233,528,823 | -5.29% | 378 |
| opaque-bases | 194,414,940 | -21.16% | 386 |

`opaque-input`/`opaque-weights`/`opaque-bases` place the corresponding pointers
through empty inline-assembly register constraints before the call. The pointers
retain their values and all static shape/scalar knowledge remains available.
Hiding both global addresses reduces the rolled loop from 19 to 11 instructions
per product and reverses the regression. This isolates address visibility as a
trigger for the poor generated form. These controls are not proposed production
interfaces.

`explicit-unroll3` copies the pinned INT8 reference function into a diagnostic
namespace and adds `#pragma GCC unroll 3` only to its channel loop. It reaches
146,068,343 instructions while adding only two bytes to the stem wrapper.
`unroll-loops` applies GCC's function-local `optimize("unroll-loops")` attribute
to the existing node wrapper. It reaches 126,483,738, with wrapper size increasing
from 396 to 646 bytes. Function-local `O3` reaches the same dynamic count, with a
580-byte wrapper. Matching counts do not imply identical binaries or dead paths.

## Validation beyond the initial fixture

The function-local unrolling variant matches complete stem outputs for all eight
existing oracle cases: baseline, zeros, maximum, zero_point, alternating, ramp,
random_42 and random_deadbeef. Each compares 401,408 bytes, **3,211,264 bytes total**.
Ordinary Spike and two matching captures pass. The zero_point case is successful
at the stem; this does not change the known downstream Softmax failure.

A separate full-model diagnostic changes only node 1's compilation attribute.
It retires **3,829,618,513 instructions**, versus current A0's 3,980,184,493,
a reduction of **150,565,980 (3.78%)**. Both full profiles agree at every PC/event;
all 64 units reconcile and all 1,000 public output bytes match. Every other unit's
instruction count is unchanged. This is **21.32% fewer instructions than B0**,
not a hardware timing claim.

## Recommendation

Keep this as a measured B1 candidate, not a global optimization-level change.
Select a small-reduction/pointer or controlled-unrolling stem implementation in
the kernel plan, compare it independently from pointwise kernels, and retain
exact border, range and quantization checks. GCC should remain the machine-code
compiler, but its profitability decisions must be checked against the emitted
assembly and repeated measurements. The existing profile already exposes the
per-node regression; future selection rules should explicitly address it.

No production compiler, kernel or build flags were changed. The current A0 ELF
and all 40 frozen B0 file hashes were verified unchanged. The full-model result
above is a diagnostic build, not a promoted checkpoint.

## Reproducibility

Archive: `build/compiler/stem-captures/1727e463d60301aa8e4bf9642eddadf5148f548fbc7b30b1361716485c339489/`.
Manifest identity: `1727e463d60301aa8e4bf9642eddadf5148f548fbc7b30b1361716485c339489`.
It preserves frozen build evidence and workspaces, compiler diagnostics,
complete fixtures, source variants, exact commands/dependency hashes, simulator
outputs and repeated captures. Commands use the original work directory recorded
in the manifest; restore it there when replaying. The kernel source notice and
original pinned header are preserved. Compact results exclude weight payloads.
