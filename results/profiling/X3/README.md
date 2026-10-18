# X3: X3 instruction profile

Full inference: **428,833,239 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `639eb6438631dac97981c82f77fe00ea20f180e81e123ffe887506c0eb91931a`; ELF: `cdac5e0a23e266db776c60ed4d88fc2e5acda93c71fa01fd206ebb5d67f7a4e2`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 428,833,239 | -4,438,445,131 | 11.350049× |
| X2-optimized | 436,158,109 | 428,833,239 | -7,324,870 | 1.017081× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 32100 bytes (derived; allocated_executable_sections).
- readonly: 4916216 bytes (derived; allocated_readonly_sections).
- bss: 1505424 bytes (derived; allocated_nobits_sections).
- initialized_writable: 20 bytes (derived; allocated_writable_sections).
- activation_scratch_workspace: 1505280 bytes (derived; static_memory_plan).
- planned_constants_and_parameters: 4915720 bytes (derived; static_memory_plan).
- peak_live_activations: 1505280 bytes (derived; static_memory_plan).
- hardware_cycles: None cycles (unavailable; CV-Wally).

## Largest inclusive execution units

| Node(s) | Implementation | Instructions |
|---|---|---:|
| 1 | project/stem_rgb3x3/int8 | 69,472,265 |
| 15 | rv64imc/depthwise_5x5/int8 | 31,599,318 |
| 8 | rv64imc/depthwise_3x3/int8 | 27,425,221 |
| 33 | rv64imc/depthwise_5x5/int8 | 25,255,717 |
| 37 | rv64imc/depthwise_5x5/int8 | 25,255,717 |
| 2 | rv64imc/depthwise_3x3/int8 | 24,261,453 |
| 30 | rv64imc/depthwise_5x5/int8 | 18,146,216 |
| 12 | rv64imc/depthwise_5x5/int8 | 17,522,745 |
| 5 | rv64imc/depthwise_3x3/int8 | 17,248,541 |
| 44 | rv64imc/depthwise_5x5/int8 | 12,249,787 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
