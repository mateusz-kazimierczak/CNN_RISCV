# X1: Xqmac8 compiler backend and Spike integration

X1 adds an eight-lane signed INT8 multiply-accumulate instruction to the accepted
software B1. It preserves B1's 32 pointwise schedules, two-pixel/two-channel tiles,
corrected biases, OHWI weights, software requantization, stem/depthwise kernels,
and physical memory plan. The custom reduction also handles each odd-pixel tail.
Unsupported pointwise geometries retain their existing scalar fallback.

## Architectural contract, version 1

```text
xqmac8 rd, rs1, rs2

sum = old_rd[31:0]
for i in 0..7:
    sum += signed8(rs1[8*i +: 8]) * signed8(rs2[8*i +: 8])
rd = sign_extend_64(sum modulo 2^32)
```

`rd` is the running accumulator, initialized with zero or a prepared bias.
Its upper 32 input bits are ignored. All three register sources are read before
writeback, including when their register numbers coincide. Reads of `x0` return
zero and writes to `x0` are discarded. Overflow wraps; there is no saturation,
rounding, exception, hidden accumulator, or memory access. The model's existing
INT32 bounds prove that its selected reductions do not overflow.

| Field | Value |
|---|---|
| Instruction width | 32 bits |
| Opcode | custom-0, `0x0b` |
| funct3 / funct7 | `0` / `0` |
| Match / mask | `0x0000000b` / `0xfe00707f` |
| rd / rs1 / rs2 | bits 11:7 / 19:15 / 24:20 |
| Lane order | lane zero in the least significant byte |
| Architectural support | RV64; illegal instruction on RV32 |
| Disabled or reserved encoding | illegal instruction |

The instruction itself imposes no memory alignment requirement. The wrapper uses
alias-safe, fixed-size `__builtin_memcpy` loads. Generated alignment arguments are
proved separately for activations and weights from the unchanged object alignment,
tensor offsets, channel strides, and eight-byte group stride. For the accepted
model those guarantees are eight and four bytes respectively. Unproven alignment
uses the portable alignment-one path. Native execution emulates the same unsigned
modular arithmetic; RV64 uses inline `.insn` with a read/write register constraint.

## Spike integration and commands

The tracked `tools/xqmac8/extension.cc` implements Spike's pinned `extension_t`
interface, including disassembly and normal register writeback logging. It is
loaded before parsing `rv64imc_xqmac8`; Spike registers the extension as `qmac8`.
The pinned revision remains `19609434bb3d83448eec8796e8f0367c868efbda`.

Ordinary and profiling Spike have different processor layouts. Separate libraries
are compiled against each variant's source/configuration headers, with transitive
header, simulator, compiler, source and library hashes in
`build/xqmac8/{ordinary,profile}/build.json`. The runner verifies those hashes and
automatically selects the matching library. Existing Spike binaries and dependency
patches are unchanged. GCC/binutils remain pinned and need no assembler extension.
The ELF architecture attribute stays RV64IMC; the X1 manifest explicitly declares
Xqmac8 and its contract version, and the audit checks actual instruction bits.

```sh
gmake compiler-x1-build
gmake compiler-x1-verify
gmake compiler-x1-tests
gmake compiler-x1-checkpoint
```

`compiler-x1-build` produces native, tensor-capture, sanitized, and RV64 binaries.
`compiler-x1-verify` compares all existing native input cases and complete RV64
baseline/random_42 outputs. `compiler-x1-tests` builds both Spike libraries and
runs the ISA and compiler tests. `compiler-x1-checkpoint` additionally collects two
identical full profiles and replays nodes 4 and 58 on every input case, with scalar
and Xqmac8 raw-dot microbenchmarks. The default parent is the accepted B1 capture;
override `X1_PARENT_CAPTURE` when restoring it at another artifact location.

Direct generation uses the same accepted defaults:

```sh
uv run --python 3.12 --with-requirements tools/compiler/requirements.txt \
  python -m compiler generate models/efficientnet-lite0-int8.tflite \
  --config X1 --output-dir build/compiler/X1
python3 tools/xqmac8/build.py
```

The automatically constructed simulator command has this form:

```sh
.deps/spike/bin/spike \
  --extlib=build/xqmac8/ordinary/libxqmac8.dylib \
  --isa=rv64imc_xqmac8 build/compiler/X1/rv64/a0.elf
```

Linux uses `libxqmac8.so`. The profile runner selects the profile library instead.
Live debugger UI integration is outside Stage 7.

## Verification and results

The ISA suite exports `build/xqmac8/tests/vectors.json`: register operands, register
numbers, expected destination bits and deterministic seed `0x514d414338`. Its
10,852 cases include 10,000 randomized cases, signed extremes, lane permutations,
wrapping, sign extension, ignored upper accumulator bits, aliases and `x0`.
A 64-instruction accumulation chain retains its accumulator between updates.
Native sanitized emulation and both Spike variants use an independent Python
arbitrary-precision oracle. Two complete fixture profiles must each count exactly
10,852 Xqmac8 retirements. Separate fixtures check disabled-extension, reserved
encoding and RV32 traps, and Spike's disassembler must print `xqmac8`.

Native capture and sanitized inference each compare 510 complete node tensors
over eight existing cases. Seven cases complete; the known all-zero-point case
preserves the existing Softmax domain failure and its 62-node prefix. Complete
1,000-byte RV64 outputs are verified for seed 1 and seed 42. The second seed uses
the same production kernel objects and a separately compiled input harness;
the performance ELF is retained.

Full profiling counts custom instructions from decoded opcode bits, checks each
selected node against its executed products divided by eight, and requires the
full-inference custom count to equal the sum of its nodes. B0/A0/B1 audits reject
custom opcodes; X1 permits only the exact Xqmac8 encoding. Rebuilding accepted B1
with the shared scheduling-header changes preserves all allocated sections and
loadable segment bytes.

The original B0 audit/disassembly sources remain byte-frozen. The shared
`tools/xqmac8/analysis.py` adapter and `tools/audit_isa_elf.py` add X1 support
without invalidating the original baseline hashes.

| Full inference, seed 1 | Accepted B1 | X1 |
|---|---:|---:|
| Retired instructions | 1,576,585,275 | 750,711,402 |
| Dynamic memory instructions | 479,017,527 | 255,349,574 |
| Xqmac8 retirements | 0 | 42,317,184 |
| Executable code bytes | 52,468 | 42,596 |
| Activation workspace bytes | 1,505,280 | 1,505,280 |

X1 retires 825,873,873 fewer instructions: a **52.38% reduction**, or a **2.1001×
instruction-count ratio**. These are ISA instruction measurements. Cycles, physical
frequency, critical path and area remain unmeasured for Xqmac8.

| Representative full-model node | B1 instructions | X1 instructions | Xqmac8 retirements |
|---|---:|---:|---:|
| 4, pointwise K=16 | 94,108,830 | 41,631,006 | 2,408,448 |
| 58, pointwise K=320, odd-pixel tail | 64,647,249 | 16,689,543 | 2,508,800 |

The isolated packed raw-dot microbenchmarks retire 36 instructions for K=16
(two Xqmac8 instructions) and 302 for K=320 (40 Xqmac8 instructions), including
fixture operand loads and result storage. Their scalar controls include existing
INT64 overflow checks; the full-model B1 comparison supplies the controlled
incremental measurement.

[Full profile and node metrics](../results/profiling/X1/README.md),
[kernel replay and microbenchmarks](../results/profiling/X1-replay/README.md), and
[compact verification gates](../results/xqmac8/verification.json) contain the
measured evidence and hashes. Raw content-addressed captures, binaries, vectors,
native dumps and simulator builds remain under ignored `build/` and `.deps/` and
must be retained separately when moving machines.

## Follow-up: 8-byte weight alignment

The controlled `X1-weights8` variant strengthens the packed-weight alignment
contract with `--xqmac8-weight-alignment 8`. Original X1 generation keeps its
4-byte weight guarantee so its accepted checkpoint remains reproducible.

All 32 selected pointwise weight tensors already have offsets divisible by eight,
and their channel rows have strides divisible by eight. The missing guarantee was
the enclosing constants object's base alignment. The variant emits
`struct alignas(8) A0Constants` and selects `Qmac8SpatialBlock<8, 8>`, allowing the
existing alias-safe packed loads to use the stronger weight guarantee. Activation
alignment remains eight. The planner carries and validates these guarantees;
an incompatible saved memory plan is rejected. Other models may require padding,
including tail padding to match the aggregate's C++ size; this model needs none.

The old weight load in the generated RV64 assembly uses two `lw`, two `c.swsp`
and one `c.ldsp` to assemble a packed operand. The aligned version uses one `ld`.
The total full-inference shift-instruction count is unchanged: the gain comes primarily from
removing loads and stack stores used to assemble the packed weights.

| Full inference, seed 1 | Original X1 | X1-weights8 |
|---|---:|---:|
| Retired instructions | 750,711,402 | 664,927,440 |
| Loads | 201,310,714 | 158,696,433 |
| Stores | 54,038,860 | 11,442,195 |
| Xqmac8 retirements | 42,317,184 | 42,317,184 |
| Executable code bytes | 42,596 | 41,952 |
| Constants and prepared parameters, bytes | 4,915,488 | 4,915,488 |
| Activation workspace bytes | 1,505,280 | 1,505,280 |

This saves **85,783,962 instructions (11.43%)** relative to X1. Two complete
retirement profiles match exactly. Nonpacked node metrics are identical, and
constant payload bytes, all tensor offsets, and all prepared parameter offsets
are preserved. This measures retired instructions; hardware cycles remain
unmeasured.

Native, capture and sanitized execution pass all eight input scenarios, including
the existing zero-point Softmax outcome; capture and sanitized runs each compare
510 complete node tensors. Complete 1,000-byte RV64 outputs pass for baseline and
`random_42`. Native/sanitized/RV64 replay passes nodes 4 and 58 across all eight
inputs plus four microbenchmarks, with matching repeat profiles. The five new
alignment tests and 42 existing memory, kernel-plan and Xqmac8 tests pass.

Reproduce the separate candidate without overwriting the original X1 directory:

```sh
gmake compiler-x1-weights8-build
gmake compiler-x1-weights8-verify
gmake compiler-x1-weights8-tests
gmake compiler-x1-weights8-checkpoint
```

The checkpoint target includes verification and the focused tests; the individual
targets are useful during iteration. The report command revalidates the original
and candidate immutable captures, current builds, output checks and replay. Its
regression-log checks expect the three existing test modules to have been run:

```sh
for suite in memory_plan kernel_plan xqmac8; do
  case "$suite" in
    memory_plan) label=memory-tests ;;
    kernel_plan) label=kernel-tests ;;
    xqmac8) label=xqmac-tests ;;
  esac
  uv run --python 3.12 --with-requirements tools/compiler/requirements.txt \
    python -m unittest discover -s tests/compiler -p "test_${suite}.py" -v \
    > "build/xqmac8/weights8-${label}.log" 2>&1
done
```

Capture focused-test output and publish the verified comparison:

```sh
gmake compiler-x1-weights8-tests > build/xqmac8/weights8-tests.log 2>&1
python3 tools/xqmac8/weight_alignment_report.py
```

[Full profile](../results/profiling/X1-weights8/README.md),
[replay](../results/profiling/X1-weights8-replay/README.md), and
[alignment gates, mnemonic counts and assembly samples](../results/profiling/X1-weights8/alignment.json)
record the comparison. Raw evidence remains in ignored `build/` and `.deps/`.

## Follow-up: retain the accumulator in an RV64 register

`X1-acc64` adds `--xqmac8-accumulator-bits 64` to the aligned-weight variant.
This chooses **register storage**, not a new arithmetic contract: each Xqmac8
still wraps at 32 bits, ignores the accumulator's upper bits, and writes a
sign-extended result. Native emulation follows the same rule after every step.

The original wrapper narrows the inline-assembly result to `int32_t` after each
instruction. GCC then emits `sext.w` before the next operation even though
Xqmac8 has already sign-extended its result. The new reduction policies retain an
`int64_t` accumulator and narrow once at the existing INT32 requantization
boundary. Single-output, blocked, spatial and odd-pixel schedules all use the
policy's accumulator type; scalar B1 and the default X1 policies retain INT32
storage. No tiling, unrolling, requantization or ISA changes are included.

| Full inference, seed 1 | X1-weights8 | X1-acc64 |
|---|---:|---:|
| Retired instructions | 664,927,440 | 624,684,209 |
| Loads | 158,696,433 | 158,243,341 |
| Stores | 11,442,195 | 10,579,299 |
| Xqmac8 retirements | 42,317,184 | 42,317,184 |
| Executable code bytes | 41,952 | 41,744 |
| Constants and prepared parameters, bytes | 4,915,488 | 4,915,488 |
| Activation workspace bytes | 1,505,280 | 1,505,280 |

This saves **40,243,231 instructions (6.05%)** relative to aligned weights.
The earlier 38.3-million estimate covered moving conversions to the end of each
reduction. Register allocation also improves: stack loads/stores and register
moves decrease. Remaining sign extensions include the required conversion at
the INT32 output boundary and existing scalar quantization operations.

Node 4 decreases from 36,814,111 to 35,609,887 instructions; node 58 decreases
from 11,569,490 to 9,013,968. Nonpacked node metrics are identical. Two full-model
profiles match exactly, with all custom counts reconciled to executed
eight-product groups. Shared-header control rebuilds preserve every allocated
section and loadable segment byte for software B1 and 32-bit-storage X1-weights8.
Frozen B0 artifacts and tools also pass their existing hash contract.

Validation passes 10,752 non-`x0` oracle vectors (including 10,000 seeded random
cases), a 64-step accumulation chain, and 72 fixtures covering all reduction
schedules, one-pixel and odd-pixel tails, and channel blocks of two and four.
These checks run under native ASan/UBSan and both Spike variants. The ISA's `x0`
behavior and encoding are unchanged; the original ISA suite retains that coverage.
All eight native input scenarios pass, with 510 node tensors compared in each
capture/sanitized run and the known zero-point Softmax outcome preserved.
Full 1,000-byte RV64 outputs pass for baseline and `random_42`; node 4/58 replay
passes all eight inputs, plus the four existing raw-dot controls, with identical
repeated profiles. The raw-dot controls retain their original 32-bit wrapper;
complete node replay exercises the optimized generated kernels. All 40 selected
compiler regressions pass.

```sh
gmake compiler-x1-acc64-build       # build the separate candidate
gmake compiler-x1-acc64-verify      # native, sanitized and RV64 output checks
gmake compiler-x1-acc64-tests       # oracle/schedule checks and 40 regressions
gmake compiler-x1-acc64-checkpoint  # all gates, controls, profiles and report
```

Checkpoint reproduction requires the retained aligned-weight parent capture,
the accepted B1 and X1-weights8 generation directories, and the pinned toolchains
and oracle evidence, as with the earlier checkpoints. The existing default
commands continue to use 32-bit accumulator storage.

[Full profile and per-node measurements](../results/profiling/X1-acc64/README.md),
[complete replay](../results/profiling/X1-acc64-replay/README.md), and
[verified accumulator gates and assembly](../results/profiling/X1-acc64/accumulator.json)
contain the measurements and identities. `python3 tools/xqmac8/accumulator_report.py`
revalidates the retained evidence. Hardware cycle, timing and area measurements
remain deferred to CV-Wally integration.

## Follow-up: retune the tile for Xqmac8

`X1-tile2x4` keeps aligned weights and 64-bit accumulator register storage, and
changes the pointwise tile from two pixels/two channels to two pixels/four
channels. The existing scheduler already supports this configuration through
`--pointwise-pixels 2 --pointwise-block 4`; no compiler or kernel source change
is needed. All 32 packed pointwise nodes have output-channel counts divisible
by four. Their remaining implementation, arithmetic, requantization, constants
and physical memory layout are preserved.

In each ordinary reduction iteration, two input loads and four weight loads
supply eight Xqmac8 instructions. The old tile uses two input and two weight
loads for four instructions. The two pointer increments and loop branch are
also shared across eight instructions. One-pixel tails share their input across
four channels while retaining the bounds-safe existing path.

| Full inference, seed 1 | X1-acc64, 2×2 | X1-tile2x4 |
|---|---:|---:|
| Retired instructions | 624,684,209 | 594,975,670 |
| Loads | 158,243,341 | 148,353,114 |
| Stores | 10,579,299 | 11,343,096 |
| Xqmac8 retirements | 42,317,184 | 42,317,184 |
| Executable code bytes | 41,744 | 49,212 |
| Constants and prepared parameters, bytes | 4,915,488 | 4,915,488 |
| Activation workspace bytes | 1,505,280 | 1,505,280 |

This saves **29,708,539 instructions (4.76%)** relative to X1-acc64. All 32
pointwise nodes improve, by 8.92–20.16%; nonpacked node metrics are identical.
Node 4 decreases from 35,609,887 to 32,310,815 instructions, and node 58 from
9,013,968 to 7,417,169. Both complete retirement profiles match exactly, and
custom counts remain consistent with executed eight-product groups.

The report identifies the 30 unique innermost backward-branch regions containing
Xqmac8 and reconciles their custom counts to the entire inference. Their packed
load count decreases from 42,470,656 to 31,891,360 (**24.91%**), including the
one-pixel tails. Neither version accesses the stack inside these reduction
loops. Larger live accumulator sets increase stores outside those loops by
763,797; total full-inference memory instructions still decrease by 9,126,430.
For the largest input-channel counts, additional address arithmetic is also
needed for weight rows beyond the load instruction's immediate range.

The tradeoff is **7,468 additional executable bytes**. Both versions' largest
individual compiler-reported stack frame is 288 bytes, and the baseline full
inference stack watermark remains 584 bytes. These are instruction measurements;
instruction-cache effects, hardware cycles and timing remain unmeasured.

Native, capture and sanitized execution pass all eight input scenarios, including
the known zero-point Softmax outcome; capture and sanitized runs each compare
510 complete node tensors. All 1,000 RV64 output bytes pass for baseline and
`random_42`. Replay validates node 4 and node 58 across all eight inputs under
native, sanitized and RV64 execution, with matching repeat profiles. The existing
10,752 register/oracle vectors, 64-step chain and 72 schedule fixtures pass
under native sanitizers and both Spike variants. Ten focused accumulator and
spatial-scheduling regressions also pass. The frozen B0 hash contract is intact.

```sh
gmake compiler-x1-tile2x4-build
gmake compiler-x1-tile2x4-verify
gmake compiler-x1-tile2x4-tests
gmake compiler-x1-tile2x4-checkpoint
```

The checkpoint target performs the checks, records two profiles, replays nodes
4/58 and publishes the verified comparison. It requires the retained X1-acc64
parent capture and pinned toolchain/oracle artifacts. Original X1 and X1-acc64
commands retain their previous defaults. There is no need for a mixed per-node
tile selection because the four-channel candidate improves every packed node.

[Full profile and per-node comparison](../results/profiling/X1-tile2x4/README.md),
[complete replay](../results/profiling/X1-tile2x4-replay/README.md), and
[tiling gates and loop assembly](../results/profiling/X1-tile2x4/tiling.json)
contain the results and artifact identities. Revalidate retained evidence with
`python3 tools/xqmac8/tiling_report.py`. Raw captures remain under ignored
`build/` and `.deps/`.

## Handoff to CV-Wally

The [CV-Wally Xqmac8 implementation](cvw-xqmac8.md) now provides the accumulating
datapath, third register read, M/W forwarding, dependency stalls and trap handling.
Run `gmake cvw-xqmac8-checkpoint` for its full-core ISA and compiler replay gates.

Implement the exact encoding and consume the exported ISA vectors. The destination
is also an implicit source: Wally needs a third source read (or an explicitly
sequenced equivalent), dependency detection, stalls/forwarding for old `rd`, and
correct behavior for consecutive accumulator updates and source/destination aliases.
Preserve `x0`, RV64 sign extension, and illegal-instruction handling. No instruction
latency or one-cycle datapath is assumed by the functional Spike model.

Hardware timing/area measurements and the X2 requantization RTL integration
remain separate subsequent work.

The implemented Stage 8 extension and incremental X2 measurements are documented
in [Xrequant v1](xrequant.md).
