# Xpostinc v1 and X3

X3 adds post-increment memory instructions to the optimized X2 schedule. Xqmac8,
Xrequant, model arithmetic, tensor layout and quantization remain unchanged.
Native execution, Spike and the [CV-Wally implementation](cvw-xpostinc.md) now
support this ISA. Software instruction-count results below remain distinct from
hardware cycle measurements.

## Architectural contract

All instructions are RV64-only, 32-bit I-format instructions. The signed 12-bit
immediate is a **byte increment**, not an address offset. Loads use custom-1
opcode `0x2b`; stores use custom-3 opcode `0x7b`. Bits 19:15 name the read/write
base register. Bits 11:7 name the load destination or store source (stores thus
use an I-format encoding, not the standard S format). Bits 14:12 select:

| funct3 | Load mnemonic | Store mnemonic | Bytes |
|---:|---|---|---:|
| 0 | xlbpi (signed) | xsbpi | 1 |
| 1 | xlhpi (signed) | xshpi | 2 |
| 2 | xlwpi (signed) | xswpi | 4 |
| 3 | xldpi | xsdpi | 8 |
| 4 | xlbupi (unsigned) | reserved | 1 |
| 5 | xlhupi (unsigned) | reserved | 2 |
| 6 | xlwupi (unsigned) | reserved | 4 |
| 7 | reserved | reserved | — |

Each legal mnemonic has mask `0x0000707f`, match `opcode | (funct3 << 12)`.
Assembly notation is `mnemonic value_register, base_register, increment`.

Snapshot both input registers. Access memory at `old(base)` with the ordinary
load/store privilege, translation, protection, endianness and memory ordering
rules. Require natural alignment even if the simulator permits misaligned base
loads/stores. On success:

- Load: write the sign- or zero-extended memory value to the destination, then
  write `old(base) + sext(imm12)` modulo 2^64 to the base.
- Store: store the low width bits of the snapshotted source, then update the base
  by the same modulo-2^64 addition.

A nonzero load destination equal to its base is reserved and raises illegal
instruction **before accessing memory**. Store source/base aliases are legal:
store the old pointer value. x0 always reads zero and discards writes. A load
into x0 still accesses memory, can fault and updates a nonzero base on success.
A base of x0 accesses address zero and discards its update. Zero and negative
increments are legal, and the updated address need not be aligned or mapped.

RV32, a disabled extension, reserved funct3 or the reserved load alias raise
illegal instruction. Natural-alignment failures raise load/store address
misaligned; ordinary access/page faults propagate unchanged. `mepc` identifies
this instruction; memory-fault `mtval` contains the **old access address**, not
the updated base. Faulting loads change neither destination nor base. Faulting
stores do not update the base; aligned ordinary RAM stores use the normal MMU
fault-before-write behavior. Device side effects follow ordinary store rules.
There is no atomic/ordering guarantee beyond ordinary loads/stores, no hidden
state, and no specified cycle latency. Two load register results are one
architectural instruction and must eventually commit together in RTL.

## Compiler policy

`generate --config X3` starts from optimized X2 (2x4 pointwise, aligned packed
weights, wide accumulator registers, selected depthwise outlining, wide ADD).
The validated kernel plan explicitly marks post-increment use. Native builds
emulate the same memory operations with alias-safe copies; RV64 emits inline
`.insn i` instructions with explicit memory operands and an early-clobber load
result to prevent the reserved destination/base alias.

Packed pointwise reductions fuse the input and weight-group increments into two
64-bit loads per reduction step, preserving reuse across both pixels and all
four output channels. Depthwise border taps use signed byte loads with the
channel stride, while interior unrolled taps retain their existing addressing.
Depthwise outputs and the pointwise odd-pixel tail use byte post-increment stores.
The stride must fit signed 12 bits. Address updates in native wrappers use
unsigned integer addresses so a final unused updated pointer does not perform
out-of-bounds C++ pointer arithmetic.

## Measured selection

The initial `all` policy applies the depthwise changes to all 16 depthwise nodes.
It retires **428,833,239 instructions**, 1.68% below optimized X2. Every packed
pointwise node improves, but ten depthwise nodes regress. The retained broad
experiment is `results/profiling/X3/`; its immutable capture includes both full
profiles and the original executable.

`--xpostinc-depthwise selected` retains the measured winning 3x3 stride-one
geometries and the 96-channel stride-two geometry: nodes **2, 5, 8, 22, 26, 56**.
It preserves the existing depthwise code elsewhere. All 32 pointwise nodes still
use post-increment loads, and their odd-pixel tails use post-increment stores.
Explicit `all`, `selected`, and `none` policies round-trip through validated
kernel plans; inconsistent or partially removed selection markers are rejected.
The CLI defaults to `all` to preserve the initial experiment. The Makefile's
recommended X3 checkpoint explicitly selects `selected`.

| Full inference, canonical input | Optimized X2 | X3 all | X3 selected |
|---|---:|---:|---:|
| Retired instructions | 436,158,109 | 428,833,239 | **423,520,020** |
| Reduction from optimized X2 | — | 1.68% | **2.90%** |
| Post-increment loads | 0 | 25,166,592 | 12,228,384 |
| Post-increment stores | 0 | 2,313,504 | 1,405,632 |
| All memory instructions | 144,277,257 | 142,478,255 | 143,701,779 |
| Integer ALU instructions | 175,062,664 | 170,732,626 | 162,999,655 |
| Executable bytes | 31,968 | 32,100 | 32,020 |

Xqmac8 remains **42,317,184** and Xrequant **7,369,032** instructions in each
experiment. Constants, prepared values and the entire physical memory plan are
byte-identical. Selected X3 keeps the **512-byte** observed stack watermark and
adds **52 executable bytes**. No selected node regresses in the canonical profile.

| Node | Optimized X2 | X3 selected | Reduction |
|---|---:|---:|---:|
| 4, short pointwise | 10,455,452 | 9,853,341 | 5.76% |
| 58, long pointwise and odd tail | 5,652,879 | 5,012,557 | 11.33% |
| 5, stride-two depthwise | 17,883,656 | 17,248,541 | 3.55% |
| 8, stride-one depthwise | 28,002,341 | 27,425,221 | 2.06% |
| 15, 5x5 depthwise control | 31,298,687 | 31,298,687 | 0% |

The byte-copy microbenchmark copies 1,024 bytes with identical output checks
outside the measured loops. Ordinary load/store plus pointer updates retire
**6,150 instructions**; post-increment addressing retires **4,102**, a **33.30%**
reduction, with exactly 2,048 custom memory retirements. This isolates the ISA
benefit; model kernels already reuse operands and use other addressing modes,
so their end-to-end improvement is smaller.

The profiler places these instructions in the **load/store** categories to keep
the instruction mix disjoint. `postincrement` separately reports their measured
counts; `custom_frequency` includes them along with Xqmac8 and Xrequant. Dynamic
counts are independently reconciled with compiler-derived pointwise, border-tap
and output schedules, including odd spatial tails. Memory-instruction counts
include cache hits and register spills; they do not measure external traffic.

## Verification and reproduction

The ISA gate checks **12,672 directed/random vectors**, all eleven encodings,
positive/negative/zero/extreme increments, sign/zero extension, store truncation,
untouched bytes, dependent pointer chains, x0 and legal store aliases. **35 precise
fault fixtures** check illegal encodings/aliases, alignment, unmapped loads/stores,
x0 accesses, `mcause`, `mepc`, `mtval`, unchanged registers and unchanged guarded
RAM on faults. Disabled-extension and RV32 cases trap. Both ordinary and profiling
Spike execute the fixtures; two ISA profiles match exactly. Native ASan/UBSan
checks independently exercise 1,008 load and 1,008 store cases across widths.

Selected X3 matches all reference outcomes across eight native/capture/sanitized
input scenarios, comparing 510 complete intermediate tensors in each captured
mode. The known zero-point input retains its original Softmax failure after the
same 62-node prefix. Two full RV64 inputs (`baseline`, `random_42`) compare every
output byte. Complete kernel replay covers 12 nodes across all eight inputs,
plus four scalar/packed dot controls: **100 fixtures** on native, ASan/UBSan and
RV64, with two matching RV64 profiles. Rebuilt B1, X1 and optimized X2 controls
preserve every allocated section and loadable segment of their accepted images.
All **232 compiler regressions** and **5 profiler regressions** pass. The compiler
suite runs in four independent processes, with complete module coverage, source
hashes and per-process logs bound in `build/xpostinc/compiler-regressions.json`.

Use the retained oracle, accepted B1/X1/X2 plans, parent capture and pinned tools:

```sh
gmake compiler-x3-spike
gmake compiler-x3-tests
gmake compiler-x3-verify
# All tests, legacy controls, broad experiment, repeated full profile and replay:
gmake compiler-x3-checkpoint
```

The recommended generation command is:

```sh
uv run --python 3.12 --with-requirements tools/compiler/requirements.txt \
  python -m compiler generate models/efficientnet-lite0-int8.tflite \
  --config X3 --xpostinc-depthwise selected --output-dir build/compiler/X3-selected
```

The extension is a separate ABI-specific plugin for each pinned Spike binary:

```sh
.deps/spike/bin/spike \
  --extlib=build/xqmac8/ordinary/libxqmac8.dylib \
  --extlib=build/xrequant/ordinary/libxrequant.dylib \
  --extlib=build/xpostinc/ordinary/libxpostinc.dylib \
  --isa=rv64imc_xqmac8_xrequant_xpostinc build/compiler/X3-selected/rv64/a0.elf
```

Linux uses `.so`. Raw binaries, vectors, logs and frozen capture evidence remain
in ignored `build/` storage. Compact tracked results are in
[the full profile](../results/profiling/X3-selected/README.md),
[replay](../results/profiling/X3-selected-replay/README.md), and
[authenticated gates](../results/xpostinc/verification.json). Keep the ignored
evidence when moving machines; JSON summaries alone do not recreate it.

## Hardware handoff

The [CV-Wally RTL implementation](cvw-xpostinc.md) now carries the base as a real
source and destination, commits both load results together, forwards both
register destinations, and suppresses writes on faults and flushes. It reuses
the Spike vectors and fault fixtures and executes an original verified X3
kernel replay ELF covering representative pointwise/depthwise schedules. See [the hardware evidence](../results/cvw/xpostinc/README.md).
Spike reductions establish ISA instruction savings; full-inference hardware
cycle speedup, critical path and area remain unmeasured.
