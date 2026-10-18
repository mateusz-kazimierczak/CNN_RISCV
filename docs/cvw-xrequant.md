# Xrequant on CV-Wally

The combined Xqmac8/Xrequant overlay implements the second custom instruction on
pinned CV-Wally `712ee9719467e9e9987cebd55926ae8e01b08770`. The upstream checkout,
B0/B1 overlay and verified Xqmac8-only overlay are preserved. Functional RTL gates
and complete X2 kernel replay are recorded in
[the hardware report](../results/cvw/xrequant/README.md).

## Architectural behavior

The encoding remains custom-0, `funct7=0`, `funct3=1`: match `0x0000100b`, mask
`0xfe00707f`. Only RV64 configurations with `XREQUANT_SUPPORTED` accept it.
It reads two explicit integer registers and writes the normal integer result;
old `rd` is not an input. Register aliases and `x0` use the ordinary register-file
and forwarding rules. It accesses no memory or hidden state.

The [existing descriptor and ISA contract](xrequant.md) is unchanged. With signed
low-32-bit accumulator `x`, nonnegative Q0.31 multiplier `M` and right shift `r`:

1. `h = floor((x*M + 2^30) / 2^31)`.
2. Round `h/2^r` to nearest, ties away from zero.
3. Return sign-extended INT32 in scale-only mode, or add the signed zero point
   using wide arithmetic, clamp to the signed INT8 bounds, and sign extend.

The two rounding stages are separate. Accumulator upper bits are ignored.
Reserved bit 63, negative multiplier, `r > 31`, reversed signed clipping bounds
or nonzero output fields in scale-only mode raise illegal instruction, including
when `rd=x0`. The destination is preserved on a fault.

## Implementation and pipeline

[The new RTL unit](../rtl/cvw/xrequant.sv) is combinational in Execute. A signed
32×32 product, rounding nudge and arithmetic shift implement the first stage;
a remainder/threshold test implements the second. The zero-point addition stays
64 bits to prevent wrapping at the INT32 extremes before clipping.

[The incremental integration patch](../rtl/cvw/xrequant.patch) applies after the
retained Xqmac8 patch. Exact decoding in Decode captures `XrequantE` using the
normal Execute stall/flush controls. The datapath takes the existing forwarded
`rs1` and `rs2`; Wally's existing load/MDU/CSR source hazards apply without a new
register-file port. Normal ALU result forwarding carries Xrequant results to
subsequent integer operations, including Xqmac8's implicit old-`rd` input.

Descriptor validation uses the forwarded Execute operand. A new
`IllegalXrequantE` input joins the existing illegal-instruction fault at the
Execute-to-Memory exception register, with the same `StallM`/`FlushM` handling.
The normal trap logic selects `mcause=2`, the original instruction for `mtval`,
and its PC for `mepc`; `TrapM` flushes writeback and younger instructions.
No descriptor fault is inferred from a stale Decode register-file value.

`tools/cvw/prepare_xrequant.py` creates `build/cvw/wally-xrequant`, copying patch
targets and linking unchanged upstream files. It checks the pinned clean revision
and refuses to replace edited owned RTL or configuration files. The integration
manifest hashes both patches, generator, configurations and owned sources.
Configurations are:

| Configuration | XLEN | Xqmac8 | Xrequant |
|---|---:|---|---|
| `arch_project_xrequant` | 64 | enabled | enabled |
| `arch_project_xrequant_off` | 64 | enabled | disabled |
| `arch_project_xrequant_only` | 64 | disabled | enabled |
| `arch_project_xrequant_rv32` | 32 | rejected | rejected |

Upstream hardwired `misa.X` is set when either extension is enabled on RV64.
Configuration macros default to disabled. This is a static configuration switch;
`misa` writes do not dynamically disable extensions in this Wally revision.

## Reproduction

With pinned sources/toolchain and Verilator available:

```sh
gmake cvw-xrequant-prepare
gmake cvw-xrequant-tests
```

To reproduce complete X2 kernel replay, first create the optimized compiler
builds if absent, then export the native/sanitized/Spike verified replay and run
its original linked ELF on RTL:

```sh
gmake compiler-x2-optimized-build
gmake cvw-xrequant-replay
gmake cvw-xrequant-checkpoint
python3 tools/cvw/xrequant/report.py
```

The default replay covers complete nodes 4 and 58 (packed pointwise), node 10
(wide ADD and scale-only requants), and nodes 33 and 37 (depthwise), across all
eight existing input scenarios, plus four raw-dot controls: 44 fixtures.
`CVW_XREQUANT_REPLAY_NODES` changes the replay selection;
`CVW_XREQUANT_REPLAY` selects an existing verified replay. It must be X2.

The SoC testbench instantiates the real core, caches, privilege unit and AHB RAM.
Programs compare their own results; the host acknowledges HTIF console mailbox
loads and observes exit. No oracle value is injected into registers or custom
results. The runner tests normal execution and periodic three-cycle external
stalls, records all source/tool/binary/ELF/log hashes, and exports the unchanged
12,256-vector ISA handoff to `build/cvw/xrequant/vectors.json`.

Coverage includes 10,000 seeded random cases, signed extremes, all right shifts,
rounding ties, clipping, wide zero-point addition, upper-bit invariance, aliases,
`x0`, dependent chains, cross-unit forwarding, invalid descriptors immediately
produced by ALU/load/multiply/divide/CSR instructions, precise trap CSRs, and
flushed younger custom instructions/stores. It separately checks neighboring
encodings, independent enables, RV32 rejection, base/M/C compatibility and the
original Xqmac8 vectors and hazards. Replay checks every output byte and guards,
and reconciles separate Xqmac8/Xrequant retirement counts against Spike.

The combinational implementation adds no custom busy protocol. Its physical
critical path, feasible frequency and area require matched synthesis and timing
analysis. Reported test-program cycles include setup and checking; full-model
RTL inference performance remains a separate unmeasured gate.
