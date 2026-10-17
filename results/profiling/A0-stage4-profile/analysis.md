# A0 findings before software optimization

The repeated full-inference capture reports **6,063,975,187 retired instructions**,
versus B0's **4,867,278,370**: an increase of **1,196,696,817 (24.59%)**. Both
profiles agree exactly and the complete 1,000-byte output matches B0. See
[the summary](summary.json), [unit table](units.csv), and [report](README.md) for
capture identities, metrics, and boundaries.

The measured ELF SHA-256 is
`ad7135f142507b3e727e61bca4b0e8dc27eff8c4e6df5c6e85aa940b103f604e`.
Its loaded sections and segments are byte-identical to the preserved Stage 4
ELF. These measurements expose the original A0 behavior; the observability work
has added no target instructions. The existing wrappers, including the Reshape
wrapper and Softmax domain preflight, remain in the measurement.

## Main measured contributions

The following groups sum disjoint execution-unit events, including their callees.
They are a different view of the same invocation counts, not extra costs.

| Group | Instructions | Full-inference share |
|---|---:|---:|
| 1×1 convolution | 4,625,142,388 | 76.27% |
| 5×5 depthwise | 609,492,171 | 10.05% |
| 3×3 depthwise | 508,528,899 | 8.39% |
| Stem convolution | 281,448,170 | 4.64% |

Invocation work outside the 64 units is only **85 instructions**. Removing the
interpreter does not by itself establish an improvement in kernel code. The
largest individual increases are node 58 (+80,155,683), node 57 (+72,174,565),
and node 4 (+71,011,044). Several depthwise units improve, but those savings do
not offset the convolution increases. The full per-node comparison is saved in
`summary.json` and uses original node identity, not addresses.

## Node 4: stack traffic in the reduction loop

In this measured A0 ELF, each instruction below retires **19,267,584** times in
node 4. The branch returns to `0x80000f4e`.

| PC | Instruction | Directly observable work |
|---|---|---|
| `0x80000f4e` | `lb x15,0(x29)` | Byte load |
| `0x80000f52` | `lb x24,0(x8)` | Byte load |
| `0x80000f56` | `c.addi x29,1` | Pointer advance |
| `0x80000f58` | `c.swsp x15,84(x2)` | Stack store |
| `0x80000f5a` | `c.ldsp x15,32(x2)` | Stack load |
| `0x80000f5c` | `c.addi x8,1` | Pointer advance |
| `0x80000f5e` | `subw x24,x24,x15` | Integer subtraction |
| `0x80000f62` | `c.lwsp x15,84(x2)` | Stack load |
| `0x80000f64` | `mulw x24,x15,x24` | Integer multiplication |
| `0x80000f68` | `c.ldsp x15,48(x2)` | Stack load |
| `0x80000f6a` | `addw x10,x24,x10` | Integer accumulation |
| `0x80000f6e` | `bne x15,x29,0x80000f4e` | Loop branch |

This loop contains **12 instructions**, including four stack accesses, compared
with the eight-instruction reduction loop documented in the
[B0 analysis](../B0/analysis.md). The four stack accesses account for 77,070,336
retirements in this node. Other changes partly offset that difference, so this
number must not be substituted for the complete node regression. This is evidence
for investigating generated loop code and register/stack use in Stage 5; it is
not a measured explanation of compiler heuristics or hardware stalls.

## Memory-instruction expansion

A0 retires **2,535,744,960** load/store instructions, versus B0's 1,245,579,605.
The differences are +918,007,739 loads and +372,157,616 stores. A0's ratio is
**6.6513 memory instructions per derived executed product**, versus about 3.267
for B0. Meanwhile, multiply retirements fall by 156,413,226. Arithmetic count
alone therefore gives an incomplete picture of this restructuring.

The A0 product denominator, 381,239,488, is derived from the pinned reference
kernel's padding-skip schedule; it is not a count of all multiply opcodes. These
memory counts include stack and metadata traffic and do not measure cache misses,
DRAM bandwidth, cycles, or CV-Wally speedup.

Kernel replay, verified GCC diagnostics, and the single-build viewer are the next
observability checkpoints. This checkpoint does not modify A0 kernels or begin B1.

## Follow-up: causal regression investigation

The [controlled investigation](../A0-regression-investigation/README.md) traces
the main regression to static shapes obscured by `memcpy` under `-fno-builtin`,
and prepared scalar values hidden by separate compilation. Explicit shape
initialization alone reduces the count to 4,176,397,081; exposing prepared
scalars as well reaches 3,980,184,493. Both diagnostic variants pass ordinary
Spike, exact seed-1 output validation and identical repeated full captures.
The original A0 baseline above is preserved. These experiments have not passed
the multi-input optimization acceptance gates and are not promoted to B1.
