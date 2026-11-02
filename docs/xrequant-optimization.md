# X2 optimization investigation

Submission mapping: selected outlining is **X2.2**, now measured through
production code in `X2-submission-02-outline`. Adding wide residual ADD registers
is **X2.3**, also the main **X2** result. The original prototype investigations
remain historical supporting evidence. See [the grouped progression](hardware-optimization-report.md).

Two compiler scheduling changes improve the new requantization stage without
changing Xrequant's encoding or arithmetic. Together they reduce full inference
from **458,701,498 to 436,158,109 retired instructions (4.91%)**. They are now
implemented in the `X2-optimized` compiler checkpoint. The original
X2 defaults and published measurements remain the comparison reference.

## Implemented compiler policies

Generate production code with both optimizations using:

```sh
uv run --python 3.12 --with-requirements tools/compiler/requirements.txt \
  python -m compiler generate models/efficientnet-lite0-int8.tflite \
  --config X2 --xrequant-depthwise-outlining selected \
  --xrequant-add-register-bits 64 --output-dir build/compiler/X2-optimized
gmake compiler-x2-optimized-checkpoint
```

The checkpoint uses the retained accepted B1/X1/X2 plans and parent captures,
plus the unchanged ISA verification from `gmake compiler-x2-tests`.

The flags are independent and default to `none` and `32`. Kernel-plan choices
record all eight outlined depthwise nodes and all nine wide-register ADD nodes;
saved-plan reconstruction rejects partial or inconsistent policy annotations.
The emitter selects a depthwise pixel function boundary and a separate
`XRequantization64` ADD policy. Both are represented in normal compiler output,
without experimental header overlays. The ADD template uses wide inputs, scale
results and sums. Before choosing it, the compiler bounds each shifted INT8
input, scales its endpoints with the independent integer oracle and proves the
sum fits INT32. The default kernel and requantization paths remain available.

Production profiling matches the combined prototype exactly: **436,158,109
instructions**, with all 17 affected nodes improving and every other node
retaining its reference count. Code is **31,968 bytes**, constants/prepared
parameters are **4,915,720 bytes**, activation workspace is **1,505,280 bytes**,
and the observed stack watermark remains **512 bytes**. The ISA contract and
both pinned Spike extensions are unchanged.

Production validation includes all eight input scenarios, 510 full tensor
comparisons in each capture mode, complete baseline and `random_42` RV64
outputs, and 92 replay fixtures. Replay covers every outlined depthwise node,
ADD and pointwise nodes 4/58 across all eight scenarios on native, sanitized
and RV64 execution. Two full retirement profiles agree. Control builds preserve
the allocated sections and load segments of accepted B1, X1 and original X2.

[Production profile](../results/profiling/X2-optimized/README.md),
[replay](../results/profiling/X2-optimized-replay/README.md), and
[verification gates](../results/xrequant/optimization-verification.json) retain
build identities, custom counts, regression results and per-node savings.
Hardware cycles, timing and area await the CV-Wally implementation.

## Controlled measurements

Each row uses the same baseline input, pinned RV64 compiler and Spike extensions.
The profiler verifies the complete 1,000-byte output and records two identical
full inference PC histograms. Every experiment preserves original constants,
prepared values, physical memory layout and dynamic custom work:
42,317,184 Xqmac8 and 7,369,032 Xrequant instructions.

| Experiment | Retired instructions | Change from X2 | Executable bytes |
|---|---:|---:|---:|
| Accepted X2 reference | 458,701,498 | — | 33,004 |
| Outline every depthwise pixel function | 437,954,122 | −4.52% | 31,844 |
| Outline selected depthwise geometries | 436,487,389 | −4.84% | 32,052 |
| Keep ADD intermediates in 64-bit registers | 458,372,218 | −0.072% | 32,920 |
| Selected outlining + ADD register storage | **436,158,109** | **−4.91%** | **31,968** |
| Smaller pointwise tile, 2×2 | 495,497,748 | +8.02% | 29,984 |
| Stop unrolling depthwise filter rows | 476,694,382 | +3.92% | 29,016 |

## 1. Reduce depthwise register pressure

Inlining the pixel implementation into the outer spatial loops keeps too many
addresses, bounds and unrolled tap values live. In node 33, the X2 assembly
executes 4,014,488 `c.ldsp` and 2,202,133 `c.sdsp` instructions, plus 602,112 each
of `c.lwsp` and `c.swsp`. The border tap loop spills its input pointer, weight
pointer, loop counter and temporary values. These are compiler scheduling costs
around Xrequant, rather than work performed by the instruction itself.

Preventing pixel inlining shortens those live ranges. Nodes **33 and 37 each
fall from 32,621,022 to 24,308,261 instructions**, saving 25.48%. Applying this
uniformly improves eight nodes but regresses eight others, so the second probe
outlines only the winning geometry families: 3×3 stride-one depthwise kernels
and the 672-channel depthwise kernels. On this model these are nodes
2, 8, 22, 26, 33, 37, 41 and 56. Every other node retains its reference retirement
count. This policy is specific to the measured model and pinned GCC; it needs
explicit kernel-plan representation and profiling before general use.

The selective probe removes **9,874,501 loads and 6,278,921 stores**, a total
of 16,153,422 memory instructions. It adds 592,537 multiplies and 1,481,527
conditional branches. Retired instruction savings therefore do not determine
the hardware cycle savings; CV-Wally must measure that tradeoff.

Reducing row unrolling alone is worse overall. Keep the existing unrolling and
control the function boundaries first.

## 2. Preserve wide ADD intermediates

Xrequant reads only the low INT32 source bits and returns a sign-extended result.
The original C++ ADD interface narrows both scale-only results and its inputs to
`int32_t`. A probe keeps these register values and the sum as `int64_t` until
Xrequant consumes their low bits. Assembly loses one instruction per residual
ADD output element, saving **329,280 instructions** across all nine ADD nodes.
Node 10 drops from 1,128,985 to 1,053,721 instructions.

The instruction's two rounding stages, descriptors and low-32-bit interpretation
are unchanged. This model's shifted INT8 inputs and scaled sums fit INT32;
keeping the C++ intermediates wide does not introduce a new arithmetic result.
The implemented compiler policy checks that bound before selecting wide storage.

## Other checks

The X1 2×4 pointwise tile remains preferable after Xrequant fusion. A 2×2 probe
regresses all 32 packed pointwise nodes and adds 36,796,250 full inference
instructions. Larger spatial tiles remain an unmeasured follow-up; they might
amortize weight and descriptor loads, but also increase register pressure.

Descriptor alignment is already handled: packed parameters have an 8-byte
alignment guarantee and use alias-safe 64-bit loads. The two-pixel pointwise
epilogue reuses each descriptor for both outputs. FC and ADD descriptors are
compile-time constants. There is no demonstrated equivalent of X1's earlier
misaligned weight-load problem to fix here.

The combined prototype passes native output checks and capture/sanitizer
comparisons on all eight scenarios, including all **510 available node tensors**
in each capture mode. The documented `zero_point` Softmax outcome remains
status 2 after its 62 valid prefix tensors. Complete RV64 baseline and
`random_42` outputs match all 1,000 bytes. Replay covers nodes 4, 10, 33 and 37
on all eight scenarios using native, sanitized and RV64 execution with repeated
retirement profiles. Replay dependency hashes confirm that it compiles the
experimental headers.

## Reproduce

For the historical investigation, `tools/xrequant/investigate.py` prepares compiler-header overlays beneath
separate generated directories. The standard builder snapshots their actual
dependency bytes. It reads original header bytes from the retained X2 capture
so the historical probes remain reproducible after production evolves.
No production header or simulator is modified. Run from the
repository root with the retained oracle, pinned toolchains and X2 parent capture.

```sh
for variant in tile2x2 dw-noinline dw-rowunroll add64 dw-selective combined; do
  uv run --python 3.12 --with-requirements tools/compiler/requirements.txt \
    python tools/xrequant/investigate.py prepare --variant "$variant"
  uv run --python 3.12 python tools/build_a0.py build --kind rv64 \
    --generated-dir "build/compiler/X2-investigate-$variant"
  uv run --python 3.12 python tools/profile_compiler.py run \
    --build-manifest "build/compiler/X2-investigate-$variant/rv64/build.json" \
    --checkpoint "X2-investigate-$variant" \
    --parent build/profiling/compiler/1f04302f3bd8362f711fa77acceafcc13c9e34946539e3dd8878639deb81cf64 \
    --results-dir "build/xrequant/investigation/$variant"
done

for kind in native capture sanitized; do
  uv run --python 3.12 python tools/build_a0.py build --kind "$kind" \
    --generated-dir build/compiler/X2-investigate-combined
  uv run --python 3.12 python tools/build_a0.py compare --kind "$kind" \
    --generated-dir build/compiler/X2-investigate-combined
done
uv run --python 3.12 python tools/xqmac8/full_input.py \
  --generated-dir build/compiler/X2-investigate-combined
uv run --python 3.12 python tools/profile_compiler.py replay \
  --build-manifest build/compiler/X2-investigate-combined/rv64/build.json \
  --host-build-manifest build/compiler/X2-investigate-combined/native/build.json \
  --nodes 4,10,33,37 --cases all \
  --output-root build/compiler/X2-investigate-replay \
  --results-dir build/xrequant/investigation/replay
uv run --python 3.12 python tools/xrequant/investigate.py report
```

The [verified measurement record](../results/xrequant/optimization-investigation.json)
contains individual capture IDs, ELF and overlay hashes, per-node deltas,
memory counts and validation gates. The combined performance capture is
`23d20c293ecab3606820866a3f1d4e5db6f4c55999b3070927d46180f84fd7c0`.
Raw immutable captures remain under ignored `build/` directories.
