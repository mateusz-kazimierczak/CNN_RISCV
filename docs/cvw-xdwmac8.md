# Xdwmac8 on CV-Wally

The fourth project overlay implements the [eight-lane bank ISA](xdwmac8.md) on
pinned CV-Wally `712ee9719467e9e9987cebd55926ae8e01b08770`. It retains Xqmac8,
Xrequant, and Xpostinc and does not modify the pinned checkout or earlier overlays.
See the [hardware checkpoint](../results/cvw/xdwmac8/README.md) for verified results.

## Datapath and architectural state

The shared E-stage multiplier block produces eight signed INT8 products for
both Xqmac8 and Xdwmac8. Xqmac8 uses its original adder-tree reduction and
implicit old-rd accumulator. Xdwmac8 uses eight independent 32-bit additions;
each wraps modulo 2^32 without inter-lane carries. Four set/get forms move
pairs through one ordinary RV64 GPR. No extra GPR read/write ports are added.

Each hart instance owns a 256-bit architectural bank and a 256-bit pending
M-stage snapshot. E reads the newer pending snapshot when present, otherwise
the committed bank. This forwards changes to untouched pairs as well as the
selected pair and permits consecutive set/MAC/get instructions without a bank
serialization stall. Sources use the existing normal and post-increment
forwarding and load/MDU/CSR hazard logic. Get results use the normal integer
result path, register writeback, and forwarding.

The bank commits on the M-to-W acceptance edge, with the same
`!StallW && !FlushW` retirement condition used by the core monitor (`StallM`
and `StallW` are equivalent in this pinned pipeline). Only a valid decoded MAC
or set creates a pending write. Ordinary pipeline flushes clear the pending
snapshot; a trap or interrupt in M suppresses its commit. A held instruction
cannot add its products repeatedly. The full eight-lane result commits at one
clock edge. Bank reads and writes have no memory effects.

Reset clears committed and pending state. Traps preserve committed state.
The bare-metal bank is caller-clobbered, with explicit four-pair save/restore
for interrupt handlers or task switches that use it. There is no automatic
XS/dirty-state CSR protocol. S/U access follows the ISA's unrestricted bank
contract. Tests exercise both lower privilege modes and interrupted bank users.

## Decode and configurations

The incremental [patch](../rtl/cvw/xdwmac8.patch) applies after the existing
three patches; [the arithmetic/bank modules](../rtl/cvw/xdwmac8.sv) are owned
copies in the new overlay. Exact decode checks every reserved operand bit and
requires RV64 plus `XDWMAC8_SUPPORTED`. MAC and set do not write a GPR. Get
writes only its explicit destination, with x0 discarding the value.

`ARCH_PROJECT_XDWMAC8_ENABLED` defaults to zero. Hardwired `misa.X` includes the
new enable on RV64; writing misa does not switch the static configuration.
All configuration names begin with `arch_project_xdwmac8`:

| Suffix | XLEN | Bank | Earlier extensions | Purpose |
|---|---:|---|---|---|
| none | 64 | on | on | combined core |
| `_off` | 64 | off | on | disabled-instruction traps |
| `_only` | 64 | on | off | independent enable, shared multipliers |
| `_rv32` | 32 | rejected | rejected | RV32 legality |
| `_vm` | 64 | on | on | S/U and PMP coverage |

`prepare_xdwmac8.py` creates `build/cvw/wally-xdwmac8`, verifies the clean pinned
revision, links unchanged files, and refuses to discard edited owned files or
configurations. Its manifest binds all patches, copied RTL and configurations.

## Functional verification

The SoC testbench uses the actual Wally core, caches, privilege/trap unit and
AHB RAM. Programs check their own arithmetic and every output byte. The host
acknowledges only HTIF console mailbox reads; it does not supply operand or
result values. A targeted timer interrupt is the only injected interrupt source.
The bank is independently asserted stable except at reset or legal retirement.

The original Spike vector ELF runs unchanged, with 10,256 arithmetic vectors,
context save/restore, x0 and register aliases, lane overflow and 64 dependent
MACs. Combined and bank-only cores each run it normally and with periodic
external stalls. The monitor reconciles MAC and all eight pair-transfer counts
separately. Directed fixtures test source forwarding, bank dependencies,
load/MDU/CSR producers, post-increment primary and base results, wrong-path
operations, eight reserved encodings, disabled and RV32 forms, precise older
load/store/descriptor/ecall faults, and interrupted MAC/set reexecution.

A separate two-instance RTL test checks independent bank storage, warm reset,
reset with an update pending, stalls, and trap flushes. Earlier Xqmac8,
Xrequant and Xpostinc vectors and hazard programs execute on the combined core.
Overlay tests check idempotence, ownership, prior-overlay isolation and decode
agreement with the independent software contract.

The compiler checkpoint executes an **unchanged verified X4 replay ELF** for
all 16 depthwise layers and pointwise controls 4 and 58 on baseline and random_42,
plus four raw-dot controls: 40 fixtures. Native, ASan/UBSan and repeated Spike
checks precede RTL execution. The software-prepared border correction tables
are part of that original ELF. No padding or quantization behavior is emulated
by the host. All custom retirement classes reconcile with Spike.

## Reproduce

With pinned dependencies, Verilator and the project toolchain installed:

```sh
gmake cvw-xdwmac8-prepare
gmake cvw-xdwmac8-tests
# Export the software-verified X4 replay and execute its original ELF:
gmake cvw-xdwmac8-replay
gmake cvw-xdwmac8-checkpoint
python3 tools/cvw/xdwmac8/report.py
```

`cvw-xdwmac8-tests` requires the existing `compiler-x4-tests` Spike handoff;
regenerate it if absent. The replay exporter uses the saved X4 production and
native builds from `compiler-x4-checkpoint`.
`CVW_XDWMAC8_REPLAY`, `CVW_XDWMAC8_REPLAY_NODES` and
`CVW_XDWMAC8_REPLAY_CASES` select another verified X4 replay or export selection.

Program cycle counts include setup, caches, console and self-checks. Kernel
replay is not full inference. Full-inference RTL cycles, matched CPI comparisons,
synthesis area and achievable clock frequency are not measured by this
checkpoint. The E-stage bank forward/add and product paths require physical
synthesis and timing analysis before a hardware speedup claim.
