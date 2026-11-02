# Xrequant v1 and X2

Submission mapping: the original `X2` checkpoint is **X2.1**. Main **X2**
means **X2.3**, the final `X2-optimized` configuration after selected depthwise
outlining and wide residual ADD registers. See [the hardware-era progression](hardware-optimization-report.md).

X2 adds exact requantization to the optimized X1 2×4 schedule, aligned weights,
and 64-bit accumulator register storage. The assignment's §3 requires both MAC
and requantization instructions; X2 is the incremental requantization experiment
regardless of §4's optional-extension wording. The separate
[CV-Wally implementation](cvw-xrequant.md) now supports both custom instructions.

## Architectural contract

`xrequant rd, rs1, rs2` is an RV64-only, 32-bit R-type instruction: custom-0
opcode `0x0b`, funct3=1, funct7=0; match `0x0000100b`, mask `0xfe00707f`.
Xqmac8 retains funct3=0. Only these exact encodings are allowed in X2.

`rs1[31:0]` is a signed accumulator; its upper bits are ignored. `rs2` is:

| Bits | Meaning |
|---|---|
| 31:0 | Nonnegative Q0.31 multiplier M; bit 31 must be zero |
| 37:32 | Unsigned right-shift exponent r, 0..31 |
| 45:38 | Signed INT8 output zero point z |
| 53:46 | Signed INT8 minimum lo |
| 61:54 | Signed INT8 maximum hi |
| 62 | Scale-only mode |
| 63 | Reserved, must be zero |

In both modes, compute in sufficiently wide signed arithmetic:

```text
x = signed32(rs1[31:0])
h = floor((x*M + 2^30) / 2^31)
s = round_nearest_ties_away_from_zero(h / 2^r)
```

This preserves the pinned TFLM/gemmlowp **two rounding stages**, including
negative halfway cases. It is not one rounded multiply/shift. For example,
x=1, M=2^30 and r=1 produce 1, whereas a single rounding of 0.25 produces 0.
Products and zero-point addition use wide intermediates without wraparound.
With legal M and x, h and s fit INT32.

- **Output mode (bit 62=0):** write `clamp(s+z,lo,hi)`, sign-extended to 64 bits.
- **Scale-only mode (bit 62=1):** write s sign-extended to 64 bits. z, lo and hi
  must all be zero. This preserves INT32 intermediates in residual ADD.

Snapshot both sources before writeback, including rd=rs1, rd=rs2 and all-source
aliases. Old rd is not an implicit source. x0 reads zero and ignores writeback;
parameter validation still occurs for rd=x0. The instruction accesses no memory,
has no hidden state and does not modify arithmetic flags or configuration CSRs.

RV32, a disabled extension, reserved encoding/descriptor bits, M with bit 31 set,
r>31, lo>hi, or nonzero output fields in scale-only mode raise illegal instruction
before writeback. A zero descriptor is valid and returns zero in output mode.
Native emulation traps on invalid descriptors as well. Latency is unspecified.

The first version supports the nonpositive multiplier shifts used by the model's
convolution, depthwise, FC and ADD operations. Positive-shift Softmax scaling,
boundary conversions and average-pool rounding retain their software paths.
INT16 final outputs are outside this descriptor format.

## Compiler and simulator integration

`generate --config X2` derives the full X1 2×4 selection and changes output
requantization only. All 49 convolution/depthwise nodes consume offline packed
per-channel descriptors. They replace the existing multiplier and shift arrays,
using the same eight payload bytes per channel; parameter padding guarantees
8-byte-aligned alias-safe loads. Prepared IR, corrected biases, original weights,
activation tensors and scratch allocation are preserved. FC parameters and all
three ADD descriptors are compile-time constants. ADD issues two scale-only
instructions and one fused output instruction per output element.

Xqmac8's pinned extension and both simulator binaries are preserved. A separate
`tools/xrequant/extension.cc` plugin is built against ordinary/profile Spike's
respective headers and processor layouts. The configuration-aware runner uses:

```sh
.deps/spike/bin/spike \
  --extlib=build/xqmac8/ordinary/libxqmac8.dylib \
  --extlib=build/xrequant/ordinary/libxrequant.dylib \
  --isa=rv64imc_xqmac8_xrequant build/compiler/X2/rv64/a0.elf
```

Linux uses `.so`. Profiling selects both matching profile libraries. The shared
bit decoder distinguishes Xqmac8 and Xrequant. B0/A0/B1 reject custom encodings,
X1 permits only Xqmac8, and X2 permits both and requires both to be present.
Full profiling and replay reconcile each opcode's actual dynamic count with the
compiler-declared number of eight-product groups or output scaling operations.

## Measurements

| Full inference, baseline input | X1 2×4 | X2 |
|---|---:|---:|
| Retired instructions | 594,975,670 | 458,701,498 |
| Xqmac8 | 42,317,184 | 42,317,184 |
| Xrequant | 0 | 7,369,032 |
| Loads | 148,353,114 | 145,258,575 |
| Stores | 11,343,096 | 15,172,104 |
| Executable bytes | 49,212 | 33,004 |
| Constants and prepared parameters | 4,915,488 | 4,915,720 |
| Activation workspace | 1,505,280 | 1,505,280 |
| Measured stack watermark | 584 | 512 |

X2 saves **136,274,172 instructions (22.90%)**. Code shrinks by 16,208 bytes.
The constants increase by 232 bytes from alignment padding. Dynamic memory
instructions increase by 734,469 (0.46%): stores rise despite fewer loads.
Depthwise nodes 33 and 37 regress by 3,068,522 and 3,062,886 instructions;
57 other affected nodes improve. The uniform X2 backend retains these regressions
in its results; selective software fallback or register-allocation tuning is
subsequent work, not hidden inside the comparison.

| Node | X1 instructions | X2 instructions |
|---|---:|---:|
| 1, RGB stem | 78,960,244 | 69,472,265 |
| 4, pointwise | 32,310,815 | 10,455,452 |
| 8, depthwise | 38,351,741 | 29,421,252 |
| 10, residual ADD | 4,211,880 | 1,128,985 |
| 58, pointwise with odd-pixel tail | 7,417,169 | 5,652,879 |
| 61, fully connected | 6,931,437 | 6,892,036 |

Two full-inference event/PC profiles agree exactly. These measurements describe
retired instructions, not hardware cycles, timing or area. One Xrequant may take
multiple cycles; multiplier reuse and forwarding need CV-Wally evaluation.

## Validation and reproduction

`tools/xrequant/test.py` compares against an independent Python oracle and pinned
TFLM on 12,256 directed/random/alias/x0 vectors, including 10,000 seeded random
cases. Native checks use ASan/UBSan. Both Spike variants execute the vectors,
a real 64-instruction dependency chain, 18 trap fixtures and a disassembly check.
The two ISA profiles each count exactly 12,320 Xrequant retirements and agree.
Vectors are exported to `build/xrequant/tests/vectors.json` and reused unchanged by RTL verification.

Native/capture/sanitized verification covers all eight inputs, with 510 complete
node tensors in each capture/sanitized run. The known zero-point Softmax failure
and 62-node prefix remain identical. Full RV64 outputs compare all 1,000 bytes for
baseline and `random_42`. Replay covers nodes 1,4,8,10,58,61 on all eight inputs,
plus four raw-dot controls: 52 fixtures under native, sanitized and RV64 execution.
B1 and X1 control rebuilds preserve allocated sections and loadable segments.
Frozen B0 files and tools retain their existing hash contract. All 224 compiler
regressions and five profiler regressions pass.

```sh
gmake compiler-x2-build
gmake compiler-x2-verify
gmake compiler-x2-tests
gmake compiler-x2-checkpoint
```

The checkpoint also refreshes A0 regression fixtures, runs the full compiler and
profiler regressions, builds legacy controls, records profiles and replay, and
publishes verified gates. It requires the retained X1 2×4 parent capture,
accepted B1/X1 generation directories, pinned toolchains and oracle artifacts.

[Full profile](../results/profiling/X2/README.md),
[replay](../results/profiling/X2-replay/README.md), and
[verification gates](../results/xrequant/verification.json) record measured
identities and PASS/FAIL/BLOCKED gates. Raw evidence is in ignored build/.deps
artifacts and must be retained separately when moving machines.

## Hardware handoff

The subsequent [scheduling optimizations](xrequant-optimization.md) are implemented
as explicit X2 compiler policies and save another 4.91% of instructions. Run
`gmake compiler-x2-optimized-checkpoint` to reproduce their production validation.
The original X2 results above remain the reference for those comparisons.

The combined Wally overlay consumes the exported vectors and exact descriptor
rules. It implements two source reads, result forwarding, x0/alias behavior,
RV64 sign extension and precise illegal-instruction handling. The current
combinational Execute datapath includes multiplication, both rounding stages,
variable shift, wide zero-point addition and signed clipping. Physical timing
and area require matched synthesis; full-model RTL performance is unmeasured.

## CV-Wally implementation

Xrequant is now implemented in a separate combined RTL overlay with Xqmac8. See
[the implementation, precise trap path and reproduction commands](cvw-xrequant.md)
and [recorded hardware gates](../results/cvw/xrequant/README.md). Full-model RTL
performance and physical synthesis timing/area remain unmeasured.
