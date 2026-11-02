# Xdwmac8: eight independent depthwise accumulators

Submission mapping: **D1 → X4** isolates the depthwise ISA contribution;
main **X4** groups both steps and compares with X3. D1 has no separate full-model
RTL cycle measurement. See [the hardware-era progression](hardware-optimization-report.md).

X4 adds a per-hart bank of eight INT32 accumulators to the Spike/compiler path.
D1 measures the same zero-point hoisting on scalar X3 kernels, before adding the
bank. The [CV-Wally implementation](cvw-xdwmac8.md) now verifies the same ISA
and original compiler kernels in RTL; full-inference cycle measurements remain
outside the software checkpoint.

## Instruction contract, version 1

All instructions are 32-bit, RV64 only, using custom-0 (`0x0b`). The bank is
`A[0..7]`; lane 0 is the least significant byte. Set/get pair 0 contains lanes
0 and 1; pair 3 contains lanes 6 and 7. Unused fields are reserved and must be
zero. The extension name passed to Spike is `xdwmac8`.

| Assembly | funct3 | funct7 | Register fields | Effect |
|---|---:|---:|---|---|
| `xdwmac8 rs1, rs2` | 2 | 0 | rd=0 | `A[i] += sext8(rs1[8*i+:8]) * sext8(rs2[8*i+:8])`, independently for i=0..7 |
| `xdwsetP rs1` | 3 | P=0..3 | rd=rs2=0 | `A[2P]=rs1[31:0]`, `A[2P+1]=rs1[63:32]` |
| `xdwgetP rd` | 4 | P=0..3 | rs1=rs2=0 | `rd={A[2P+1],A[2P]}` |

Arithmetic wraps modulo 2^32 independently in each lane; no saturation, carries
between lanes, activation offset, memory access, or floating-point state.
Sources are sampled before any update; rs1=rs2 and x0 sources are legal. A get
to x0 discards the value and preserves the bank. All eight lane updates retire
atomically. Disabled extension, RV32, and reserved encodings raise illegal
instruction without changing the bank. Existing custom encodings remain intact.
The Python contract, native implementation, and Spike plugin use separate
implementations of the arithmetic.

The bank resets to zero per hart and otherwise survives traps. The bare-metal
ABI treats it as caller-clobbered. Each generated block initializes all eight
lanes before using them. An interrupt handler or task switch that uses this ISA
must save all four get pairs and restore all four set pairs before resuming the
interrupted computation. There is no XS/dirty-state CSR or OS context protocol
in this version. A bank session cannot span an unsaved nested bank user.

The C++ intrinsics use explicit GPR operands and a dependency token to order
hidden-state operations. They do not introduce a memory fence. Loads/stores
remain ordinary memory operations or existing Xpostinc operations. Spike owns
a distinct bank in each extension instance; an interleaved two-hart test
verifies isolation.

## Border-exact zero-point hoisting

For valid taps V at output position (y,x), and input offset d=-zero_point:

```
sum((q[t] + d) * w[t]) + bias
  = sum(q[t] * w[t]) + (bias + d * sum(w[t], t in V))
```

The compiler deduplicates valid filter rectangles and prepares an INT32 corrected
bias vector per rectangle. A per-output-pixel region map selects the vector.
The interior includes all taps; corners and edges include only valid taps.
Skipped padding never adds an offset contribution. The correction is computed
from the original immutable weights and quantization data, without changing
the original constants or activation placement. Both D1 and X4 use the same
correction tables and unchanged Xrequant descriptors.

Before selecting the transformation, the compiler bounds every possible
bias-first INT32 prefix using independent per-weight minima and maxima over
raw signed INT8 activations. It rejects a transformation that could overflow.
Saved kernel plans are rebuilt from the graph and compared, including every
table entry. There is no runtime +128 inside the MAC and no double correction.

## Kernel schedule

NHWC activations and 1HWO filters have adjacent channels contiguous. For every
output pixel and block of eight channels, X4 loads four corrected bias pairs,
sets the bank, loads eight activation/weight bytes per valid spatial tap,
executes one MAC, gets four pairs, then applies eight unchanged Xrequant
operations and stores eight bytes. Interior taps are unrolled; borders are
clipped before the channel-block loop. Eight-byte alignment is proven from
physical offsets and channel stride. The generic native-tested fallback handles
unaligned channel strides and scalar channel tails without over-reading.
All 16 depthwise layers in this model have channel counts divisible by eight.

The full inference retires 3,831,052 bank MACs (30,648,416 independent products)
and 288,316 of each of the four set and four get instructions. Profiling checks
each mnemonic count independently for every execution unit, including borders.
Pointwise schedules and requantization counts are unchanged.

## Reproduce

```
make compiler-x4-checkpoint
```

Individual targets: `compiler-d1-verify`, `compiler-x4-verify`,
`compiler-x4-tests`, `compiler-x4-controls`, `compiler-x4-regressions`,
`compiler-x4-profile`, and `compiler-x4-replay`.
The complete checkpoint builds native, full-tensor capture, ASan/UBSan, and RV64
variants, verifies two full RV64 inputs, replays every depthwise layer and two
pointwise controls, rebuilds prior configurations, and authenticates results.
Spike libraries are built separately for ordinary and profiling ABIs without
modifying either pinned Spike source tree.

See [the validated checkpoint](../results/profiling/X4-verification.md),
[zero-point-only profile](../results/profiling/D1/README.md), and
[packed profile](../results/profiling/X4/README.md).
Retired instruction ratios are not hardware cycle speedups.
