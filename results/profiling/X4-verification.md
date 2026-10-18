# Validated depthwise optimization checkpoint

| Configuration | Full inference instructions | Depthwise instructions |
|---|---:|---:|
| X3-selected | 423,520,020 | 245,087,905 |
| D1 | 389,566,544 | 211,134,429 |
| X4 | 229,114,977 | 50,682,862 |

Zero-point hoisting alone removes 33,953,476 instructions (8.02%).
The bank removes another 160,451,567 (41.19% of D1).
Combined reduction: **45.90%**, or **1.849×** fewer full-inference instructions.
Depthwise reduction: **79.32%** (4.836×).

## Verification

- 238 compiler regressions and 5 profiler tests passed.
- 10,256 ISA vectors passed native sanitizers and ordinary/profile Spike, including lane wrap, aliases, dependency chains, context save/restore, reset state, and eight precise reserved-encoding traps. Disabled/RV32 traps and interleaved two-hart isolation passed.
- D1 and X4 each match all eight reference input cases in native, full capture, and ASan/UBSan builds; capture and sanitized modes each compare 510 complete tensors. The existing zero-point-input Softmax failure remains status 2 after 62 matching tensors.
- Both configurations match all 1,000 output bytes for baseline and random_42 on RV64 Spike. Two full event/PC captures agree exactly for each configuration.
- 148 replay fixtures pass native, sanitized, and RV64 builds, covering all 16 depthwise layers and two pointwise controls across eight cases, plus four dot-product controls.
- Per-unit bank MAC/set/get, Xqmac8, Xrequant and post-increment retirements reconcile with independent schedule counts. Untargeted execution-unit counts are unchanged.
- Prior B1/X1/X2/X3 allocated sections and load segments are byte-identical. Frozen B0 inputs remain intact.

## Footprint and remaining bottlenecks

Prepared constants and parameters grow by 756,320 bytes for region maps and corrected bias vectors. Activation workspace remains 1,505,280 bytes.
Executable code: 32,020 → 38,572 bytes.
The stem is now the largest unit: 69,472,265 instructions (30.3%). All depthwise layers together account for 22.1%.
Counts measure retired instructions, not hardware speedup, cache misses, or DRAM traffic. The new accumulator bank is implemented in Spike and compiler only; CV-Wally integration remains deferred.

Reproduce: `make compiler-x4-checkpoint`. The adjacent JSON binds immutable captures, ELFs, numerical evidence, replay, tests, extension identities and legacy controls.
