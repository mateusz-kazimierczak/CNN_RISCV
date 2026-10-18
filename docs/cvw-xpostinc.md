# Xpostinc on CV-Wally

The Xqmac8/Xrequant/Xpostinc overlay implements the [X3 memory ISA](xpostinc.md)
on pinned CV-Wally `712ee9719467e9e9987cebd55926ae8e01b08770`.
The [hardware report](../results/cvw/xpostinc/README.md) records functional
verification and execution of the original compiler-generated X3 replay ELF.
The pinned upstream checkout and earlier overlays are preserved.

## Instruction behavior

RV64 instructions use I-format signed byte increments: custom-1 `0x2b` loads
(`funct3=0..6`) and custom-3 `0x7b` stores (`funct3=0..3`). The memory address is
the old `rs1` value. Stores read their value from bits 11:7. Successful access
updates `rs1` with old base plus sign-extended imm12, modulo 2^64. Loads also
write their sign/zero-extended memory value through the normal load path.

Nonzero equal load destination/base registers are illegal before memory access.
Store source/base aliases store the old base. x0 discards results without
suppressing an access or its faults. Natural alignment is mandatory even when
ordinary misaligned accesses are enabled. Access/page faults and trap CSRs use
the original address. Faults and flushed instructions cannot update the base;
a faulting load also preserves its value destination. These are ordinary memory
operations with the existing privilege, translation, protection and ordering.

## Pipeline changes

[The incremental RTL patch](../rtl/cvw/xpostinc.patch) applies after the retained
Xqmac8 and Xrequant patches. Decode validates the entire legal instruction family,
including the load alias restriction and RV64/configuration gates. The store
value field is routed to the existing second register source and its hazard
logic. Loads clear the unused second source so immediate bits cannot create
false dependencies.

Execute sends the forwarded old base to the LSU address register. The existing
ALU concurrently computes base plus immediate. That sum and its base destination
travel through M and W with the normal stall/flush controls. No custom busy
state or extra arithmetic cycle is introduced.

The integer register file adds a second write port, enabled only with RV64
Xpostinc. Both load results use the same falling clock edge in W; ordinary trap
flushes suppress both. Legal loads have distinct nonzero destinations. Stores
use only the base write port. Existing cache, bus, load-result and exception
paths handle the memory access.

Each integer operand can forward either normal results or updated bases from M
and W. Selection checks both destinations of the younger M instruction before
either destination in W. This preserves write-after-write priority. The same
paths feed ALU operands, store data, Xrequant inputs and Xqmac8's implicit old-rd
accumulator. Ordinary load/MDU/CSR hazards still stall consumers until their
normal result is available; the updated base itself is ready in M.

The LSU checks the original address for custom natural-alignment faults and
suppresses a bad request before translation, spill handling or bus/cache writes.
This preserves mandatory alignment when `ZICCLSM_SUPPORTED=1` and gives alignment
priority even for an unmapped virtual address. Ordinary misaligned-access
behavior is preserved and separately exercised across a cache-line boundary.

## Configuration and verification

`tools/cvw/prepare_xpostinc.py` creates `build/cvw/wally-xpostinc`. It verifies the
clean pinned revision, owns regular copies of changed files, links unchanged
sources, and refuses to discard edited owned files/configurations. Its manifest
records patch, generator, configuration and source hashes.

| Configuration suffix | XLEN | Xqmac8/Xrequant | Xpostinc | Additional coverage |
|---|---:|---|---|---|
| none | 64 | enabled | enabled | combined datapath |
| `_off` | 64 | enabled | disabled | illegal instruction |
| `_only` | 64 | disabled | enabled | independent enables |
| `_rv32` | 32 | rejected | rejected | RV32 rejection |
| `_misaligned` | 64 | enabled | enabled | ordinary Zicclsm accesses |
| `_vm` | 64 | enabled | enabled | Sv39, S/U, PMP, TLB misses |

All names start with `arch_project_xpostinc`. Configuration macros default to
zero. Hardwired `misa.X` is set when any supported project extension is enabled
on RV64; writes to `misa` do not dynamically switch these static enables.

The Verilator testbench instantiates the actual Wally core, caches, privilege
unit and AHB RAM, with assertions enabled. Programs check their own results.
Only HTIF console mailbox loads are acknowledged by the host; no operand or
oracle result is injected into the core. Normal and periodic external-stall
runs exercise the same instruction/fault fixtures as Spike.

The suite checks 12,672 vectors, sign/zero extension, truncation, negative/zero/
extreme strides, legal aliases, x0, dependency chains, M/W forwarding through
both destinations, producer hazards, and younger instructions flushed by
branches or traps. The 35 precise-fault fixtures check `mcause`, `mepc`, `mtval`,
unchanged registers and guarded memory. Additional load/store faults immediately
follow ALU, load, multiply, divide and CSR base producers. Sv39 tests check both
writeback results after a TLB miss, all eleven instruction page faults and
alignment priority. Earlier Xqmac8/Xrequant vectors and hazard tests are rerun.

The compiler checkpoint executes an **unchanged verified X3 replay ELF**:
pointwise nodes 4 and 58 and depthwise nodes 5 and 8 on `baseline` and
`random_42`, plus four raw-dot controls, totaling 12 fixtures. It compares every
output byte and guards and reconciles each custom instruction class with Spike.
The selection covers short/long packed pointwise reductions, the odd-pixel
post-increment store tail, and both stride-one and stride-two depthwise borders.
The same ELF is verified on native, ASan/UBSan and Spike before RTL execution.
This is isolated kernel replay, not full inference. The larger 100-fixture
software replay remains available as an optional hardware run.

## Reproduction

With pinned dependencies, the RISC-V toolchain and Verilator available:

```sh
gmake cvw-xpostinc-prepare
gmake cvw-xpostinc-tests
```

The tests depend on the existing Spike vector handoff and copy microbenchmark;
`gmake compiler-x3-tests` regenerates those if absent. To include compiler
kernel replay, use the saved X3 builds or regenerate the software checkpoint:

```sh
# Regenerate the software checkpoint and replay if absent:
gmake compiler-x3-checkpoint
# Export and verify the smaller hardware replay, then execute its original ELF:
gmake cvw-xpostinc-replay
gmake cvw-xpostinc-checkpoint
python3 tools/cvw/xpostinc/report.py
```

`CVW_XPOSTINC_REPLAY_NODES` and `CVW_XPOSTINC_REPLAY_CASES` control the export.
`CVW_XPOSTINC_REPLAY` selects another verified X3 replay. The default is
`build/compiler/X3-cvw-replay/latest.json`. The full software replay can also run:

```sh
gmake cvw-xpostinc-checkpoint CVW_XPOSTINC_REPLAY=build/compiler/X3-selected-replay/latest.json
```

That optional 100-fixture run exceeds 1.4 billion kernel instructions, with
additional driver/checking instructions, and takes substantially longer.
Build records bind all RTL,
configuration, test-driver, tool and executable hashes; the report revalidates
those identities and each ELF/log before publishing its summary.

Reported test-program cycles include setup, cache effects, console output and
checks. Full-inference RTL cycles, CPI comparisons, synthesis area and feasible
clock frequency remain unmeasured. The extra register-file write port and wider
forwarding multiplexers require matched synthesis/timing analysis before a
physical performance claim.
