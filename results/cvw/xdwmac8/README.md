# Eight-lane depthwise bank on CV-Wally

**PASS**: 82 self-checking program runs on five real Wally SoC configurations.

- 10,256 identical Spike/RTL arithmetic vectors; 92,399 bank operations per vector run, with normal and stalled execution on combined and bank-only cores.
- Eight signed-byte multipliers are shared with Xqmac8; the bank independently accumulates all eight INT32 lanes.
- Pending-bank and GPR forwarding, load/MDU/CSR producers, post-increment primary/base consumers, x0 and aliases.
- Get-result consumers include ALU, branch, ordinary and post-increment memory, Xqmac8 old-rd, and Xrequant with M/W forwarding.
- Eight reserved encodings, every disabled/RV32 instruction, independent enables, and base/M/C compatibility.
- Older load/store/descriptor/ecall faults and wrong-path operations preserve bank state.
- Targeted M-stage MAC/set interrupts preserve the bank; explicit handler save/overwrite/restore and reexecution pass normally and under stalls.
- Two independent instances, warm reset with pending operations, S/U bank access, and earlier Xqmac8/Xrequant/Xpostinc vector and hazard regressions.
- Five overlay ownership/isolation/decode tests pass.
- Original X4 compiler ELF: **40 fixtures**, **7,146,960 output bytes** plus guards, 18 layers/controls across 2 inputs.
- Replay retires 7,662,104 MACs and 4,613,056 pair transfers, independently reconciled by mnemonic with Spike; zero unexpected traps.

[Detailed evidence](verification.json), [consumer/LSU evidence](integration-tests.json), [authenticated summary](summary.json), [per-program counts](cases.csv).

Reproduce: `gmake cvw-xdwmac8-checkpoint`. See [implementation and setup](../../../docs/cvw-xdwmac8.md).

Cycle counts in cases.csv include setup, caches, console and self-checks. This checkpoint does not measure full-inference cycles, matched speedup, physical area or achievable clock frequency. Pinned sources and earlier overlays remain intact.
