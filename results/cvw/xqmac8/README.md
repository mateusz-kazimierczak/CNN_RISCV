# CV-Wally Xqmac8 RTL verification

Status: **PASS** for the recorded functional hardware gates.

Pinned Wally: `712ee9719467e9e9987cebd55926ae8e01b08770`. Original checkout and B0/B1 overlay remain unchanged.

The real Wally SoC executes 10,852 oracle vectors (10,000 seeded random), normal/stalled dependency programs,
1,026 invalid encodings, RV32/disabled-extension traps and base-ISA/misa compatibility checks.

| Case | Custom retirements | Traps | Program retirements | Program cycles |
|---|---:|---:|---:|---:|
| arch_project_xqmac8-base | 0 | 0 | 22 | 62 |
| arch_project_xqmac8_off-base | 0 | 0 | 22 | 62 |
| arch_project_xqmac8_off-traps | 0 | 1 | 26 | 80 |
| arch_project_xqmac8_rv32-base | 0 | 0 | 22 | 86 |
| arch_project_xqmac8_rv32-traps | 0 | 1 | 26 | 104 |
| compiler-kernel-replay | 39,338,026 | 0 | 511,265,757 | 604,632,592 |
| hazards | 1,070 | 0 | 4,616 | 13,046 |
| hazards-stalled | 1,070 | 0 | 4,616 | 13,809 |
| invalid-encodings | 0 | 1,026 | 17,450 | 34,294 |
| vectors | 10,852 | 0 | 98,193 | 153,118 |
| vectors-stalled | 10,852 | 0 | 98,193 | 169,373 |

Compiler replay: **20 fixtures**, complete nodes 4/58 across all eight scenarios plus four raw-dot controls.
All **10,135,568 output bytes** compare exactly, including guards;
**39,338,026 custom retirements** reconcile with the retained Spike profile.
Replay artifact: `9d6957fb06e9695ae22fad89d0effa9ca0d72ea5b40dfb2355213fdbfe9c5a4b`.

Cycles above cover entire test programs, initialization and checking. They are not full-inference cycles or a physical clock-frequency result.
Full-model X1 performance and matched synthesis area/timing remain separate, unmeasured gates.

Reproduce: `gmake cvw-xqmac8-checkpoint`.

[Implementation and commands](../../../docs/cvw-xqmac8.md) · [Full verification](verification.json) · [Compact gates](summary.json)

Raw logs, executables and memory images are retained under ignored `build/cvw/xqmac8/`.
