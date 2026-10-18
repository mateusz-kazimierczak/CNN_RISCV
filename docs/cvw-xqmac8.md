# Xqmac8 on CV-Wally

The first custom instruction has a synthesizable implementation in the pinned
CV-Wally core. `rtl/cvw/xqmac8.patch` integrates it into Wally; the separate
`rtl/cvw/xqmac8.sv` module implements its arithmetic. The original checkout and
the B0/B1 simulation overlay are preserved.

## Architecture and pipeline

The ISA contract is identical to the compiler and Spike implementation:

```text
match = 0x0000000b, mask = 0xfe00707f
rd = sext64((old_rd[31:0] + sum_i signed8(rs1[8i+:8]) * signed8(rs2[8i+:8])) mod 2^32)
```

The exact opcode, funct3 and funct7 are checked regardless of Wally's relaxed
base-instruction decoding options. The extension is enabled by the static
`cvw_t` parameter `P.XQMAC8_SUPPORTED` and is available only when `P.XLEN == 64`.
Disabled configurations, RV32, other custom opcodes, and reserved funct fields
raise the ordinary illegal-instruction exception. `misa.X` is set only for the
enabled RV64 configuration, consistent with the
[privileged ISA's nonstandard-extension indication](https://docs.riscv.org/reference/isa/priv/machine.html).
Wally's hardwired `misa` remains unchanged by writes; no runtime extension-enable
CSR is added.

This implementation uses eight parallel signed 8×8 multipliers, a balanced
adder tree, and a 32-bit accumulator addition. The result is sign-extended to
64 bits. It is combinational within Execute, then follows the normal M/W result
and writeback path. It does not use the MDU or access memory. There is no new
multicycle busy protocol or instruction-specific latency stall. Whether this
datapath meets a desired clock period requires synthesis and timing analysis.

Old `rd` is a real third source:

- The integer register file gains an optional combinational read at `InstrD[11:7]`.
  Its value enters an E-stage pipeline register using the existing stall/flush
  convention. The port elaborates to zero when the extension is unavailable.
- E-stage forwarding selects the most recent matching M result, then W result,
  then the saved register value. This supports consecutive accumulations and
  all `rd`/`rs1`/`rs2` aliases without reading a result after its own writeback.
- Decode dependencies include old `rd`, so existing load, store-conditional,
  CSR-read, MDU and FP-conversion stall rules also protect that source.
- Flushes clear the custom operation with the ordinary instruction controls.
  Zero-register reads are zero and destination x0 discards writeback.

## Overlay and build

```sh
gmake cvw-xqmac8-prepare
gmake cvw-xqmac8-tests
```

`prepare_xqmac8.py` checks Wally revision
`712ee9719467e9e9987cebd55926ae8e01b08770` and requires its tracked sources to
be clean. It makes regular copies of the six patched files in
`build/cvw/wally-xqmac8/`, links unchanged directories/files, and adds the new
arithmetic module. It never applies the patch through a link into `.deps/cvw`.
Regeneration rejects modified owned RTL/testbench files instead of discarding
local experiments in those files.

The overlay provides three configurations:

| Configuration | XLEN | Extension flag | Xqmac8 execution |
|---|---:|---:|---|
| `arch_project_xqmac8` | 64 | 1 | Enabled |
| `arch_project_xqmac8_off` | 64 | 0 | Illegal instruction |
| `arch_project_xqmac8_rv32` | 32 | 1 | Illegal instruction |

The own configurations expand their flag into the shared parameter structure.
Other configurations default to the extension being absent. The selected M/C,
cache, RAM and branch-prediction settings follow the established B0/B1 overlay:
16 KiB instruction/data caches and 128 MiB modeled AHB RAM at `0x80000000`.
The test runner uses installed Verilator, recording its version/binary hash,
the host compiler, complete RTL input hashes and actual build command. It uses
the existing xPack RISC-V assembler/linker. On macOS it selects the matching
Command Line Tools compiler and SDK explicitly. The Linux baseline bootstrap
can provide Verilator; it does not need the compiler frontend or model oracle
for the standalone instruction tests.

## Verification

The testbench instantiates the actual `wallypipelinedsoc`, including its pipeline,
hazard unit, caches, privilege machinery and AHB RAM. It loads assembled ELF
programs. Programs check results themselves; the testbench observes architectural
completion and independently counts custom retirements and traps. Oracle values
are never forced into the datapath or register file.

The gates cover:

- All **10,852** existing contract vectors, including **10,000 seeded random**
  cases, signed extremes, lane ordering, wraparound, ignored accumulator upper
  bits, aliases, x0 and accumulation chains. Run normally and with periodic
  external pipeline stalls. RTL exports the same JSON handoff vectors.
- A **1,070-operation** dependency program, also normally and under stalls:
  immediate ALU/load/multiply/divide/CSR producers of old rd, repeated custom
  accumulations, 1,000 randomized producer/alias combinations, and wrong-path
  custom operations behind taken branches. Acceptance requires observed M/W
  accumulator forwarding and old-rd-only load/MDU/CSR stalls.
- **1,026 illegal encodings**: all 1,023 nonmatching funct3/funct7 combinations
  under custom-0, plus three other custom opcodes. Exception handlers verify
  `mcause=2`, `mepc`, `mtval`, unchanged rd and squashing of younger custom work.
- Real RV32 and disabled-extension trap tests, and base integer/compressed
  compatibility checks on all three builds, including the `misa.X` indication.

The HTIF model acknowledges console-mailbox loads in the same way as the
baseline monitor, and echoes committed console stores. It does not change
ordinary loads or computed results. This lets unchanged compiler replay drivers
print their own complete-tensor comparisons and exit through HTIF.

## Compiler kernel checkpoint

```sh
gmake cvw-xqmac8-checkpoint
```

This adds the retained, already verified X1 2×4 kernel replay to the standalone
gates. The default is `build/compiler/X1-tile2x4-replay/latest.json`; override
`CVW_XQMAC8_REPLAY` to select another verified X1 replay artifact. The runner
validates its immutable evidence and derives its custom count from saved Spike
profiles. It runs the original linked ELF, without recompiling its kernels.
X2 replay is rejected because Xrequant RTL is a later integration step.

The retained replay contains **20 fixtures**: complete nodes 4 and 58 for all
eight input scenarios, plus four raw-dot controls. The expected dynamic total
is **39,338,026 Xqmac8 retirements**. Target-side comparisons check every output
byte and guards; the host also verifies every reported fixture/status/extent
and requires the complete replay success record. The run compares **10,135,568
output bytes** exactly. Including fixture setup and checks, the complete program
retires 511,265,757 instructions and takes 604,632,592 simulated cycles. This
checkpoint is consequently much longer than `cvw-xqmac8-tests`.

[Verification record](../results/cvw/xqmac8/verification.json) contains actual
results, configuration and simulator identities, oracle/vector hashes,
dependency coverage and compiler-replay details. Raw logs, executables and
memory images remain in ignored `build/cvw/xqmac8/` storage.

Cycles in this record cover whole test programs, including initialization and
self-checking. They are not full-inference cycle counts or a clock-frequency
measurement. Full-model X1 cycle/CPI evaluation and synthesis area/timing remain
separate gates; the X1 synthesis example remains blocked until its core boundary,
memory treatment and constraints are explicitly selected.
