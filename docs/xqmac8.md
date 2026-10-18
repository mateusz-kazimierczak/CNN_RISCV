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

## Handoff to CV-Wally

Implement the exact encoding and consume the exported ISA vectors. The destination
is also an implicit source: Wally needs a third source read (or an explicitly
sequenced equivalent), dependency detection, stalls/forwarding for old `rd`, and
correct behavior for consecutive accumulator updates and source/destination aliases.
Preserve `x0`, RV64 sign extension, and illegal-instruction handling. No instruction
latency or one-cycle datapath is assumed by the functional Spike model.

CV-Wally RTL changes, hardware timing/area measurements, and the X2 requantization
instruction remain separate subsequent work.
