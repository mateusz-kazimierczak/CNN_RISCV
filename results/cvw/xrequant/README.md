# CV-Wally Xrequant RTL verification

Status: **PASS** for the recorded functional gates.

The combined overlay executes Xqmac8 and exact two-stage Xrequant on the real pinned Wally SoC, with caches, forwarding and privilege/trap logic.

12,256 oracle vectors (10,000 seeded random) plus 64 dependent requants pass in normal and externally stalled execution. 441 reserved-descriptor cases check mcause/mepc/mtval, unchanged destination/source registers and flushed younger custom/store operations, with ALU/load/MDU/CSR producers. All 1,025 neighboring encodings trap. Independent enables, RV32 traps and the original Xqmac8 vector/hazard suite pass.

| Case | Xqmac8 | Xrequant | Traps | Program retirements | Program cycles |
|---|---:|---:|---:|---:|---:|
| arch_project_xrequant-base | 0 | 0 | 0 | 22 | 62 |
| arch_project_xrequant-qmac | 10,852 | 0 | 0 | 98,193 | 153,118 |
| arch_project_xrequant_off-base | 0 | 0 | 0 | 22 | 62 |
| arch_project_xrequant_off-qmac | 10,852 | 0 | 0 | 98,193 | 153,118 |
| arch_project_xrequant_off-trap-0073128b | 0 | 0 | 1 | 26 | 80 |
| arch_project_xrequant_only-base | 0 | 0 | 0 | 22 | 62 |
| arch_project_xrequant_only-trap-0073028b | 0 | 0 | 1 | 26 | 80 |
| arch_project_xrequant_rv32-base | 0 | 0 | 0 | 22 | 86 |
| arch_project_xrequant_rv32-trap-0073028b | 0 | 0 | 1 | 26 | 104 |
| arch_project_xrequant_rv32-trap-0073128b | 0 | 0 | 1 | 26 | 104 |
| compiler-kernel-replay | 39,338,026 | 14,049,280 | 0 | 772,698,931 | 910,591,634 |
| descriptor-traps | 0 | 0 | 441 | 20,155 | 37,019 |
| descriptor-traps-stalled | 0 | 0 | 441 | 20,155 | 40,097 |
| hazards | 64 | 656 | 0 | 9,879 | 17,533 |
| hazards-stalled | 64 | 656 | 0 | 9,879 | 19,066 |
| invalid-encodings | 0 | 0 | 1,025 | 17,434 | 34,256 |
| qmac-hazards | 1,070 | 0 | 0 | 4,616 | 13,809 |
| requant-only | 0 | 12,320 | 0 | 110,412 | 172,021 |
| vectors | 0 | 12,320 | 0 | 110,412 | 172,021 |
| vectors-stalled | 0 | 12,320 | 0 | 110,412 | 190,285 |

X2 compiler replay: **44 fixtures**, nodes 4, 10, 33, 37, 58, all 8 input scenarios. All **12,845,072 output bytes** and guards compare exactly. **39,338,026 Xqmac8** and **14,049,280 Xrequant** retirements reconcile with retained Spike evidence. The original linked replay ELF runs without recompilation.

Replay artifact: `876bdbf31aff14fccaf47e9fa2907be671a7e19fe51aa83bf86790b49e9f84b6`.

Cycles above cover whole test programs, including setup and checks. Full-model RTL inference performance and synthesis timing/area remain unmeasured.

Reproduce: `gmake cvw-xrequant-checkpoint`.

[Implementation and commands](../../../docs/cvw-xrequant.md) · [Full evidence](verification.json) · [Compact gates](summary.json)

Executables, logs and vector export: ignored `build/cvw/xrequant/`. Original Xqmac8 and B0/B1 overlays are preserved.
