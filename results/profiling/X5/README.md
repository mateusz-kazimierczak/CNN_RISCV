# X5: X5 instruction profile

Full inference: **167,729,178 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `507135ccfc8d2b9644ca00b0380393938e63bc86b0bb8fce5f71c6a80ba78b77`; ELF: `75f2eddf7de3b165b7ab80733f18eafa3b197315622686289ab5ccaa8d16f8d6`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 167,729,178 | -4,699,549,192 | 29.018674× |
| X4 | 229,114,977 | 167,729,178 | -61,385,799 | 1.365982× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 38140 bytes (derived; allocated_executable_sections).
- readonly: 5724248 bytes (derived; allocated_readonly_sections).
- bss: 1505424 bytes (derived; allocated_nobits_sections).
- initialized_writable: 20 bytes (derived; allocated_writable_sections).
- activation_scratch_workspace: 1505280 bytes (derived; static_memory_plan).
- planned_constants_and_parameters: 5723752 bytes (derived; static_memory_plan).
- peak_live_activations: 1505280 bytes (derived; static_memory_plan).
- hardware_cycles: None cycles (unavailable; CV-Wally).

## Largest inclusive execution units

| Node(s) | Implementation | Instructions |
|---|---|---:|
| 4 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 9,853,341 |
| 8 | rv64imc/depthwise_3x3/int8 | 8,394,233 |
| 1 | rv64imc/stem_rgb_xqmac8/int8 | 8,086,466 |
| 2 | rv64imc/depthwise_3x3/int8 | 7,868,784 |
| 61 | project/fully_connected/int8 | 6,892,036 |
| 5 | rv64imc/depthwise_3x3/int8 | 5,646,728 |
| 58 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 5,012,557 |
| 15 | rv64imc/depthwise_5x5/int8 | 4,896,844 |
| 57 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 4,637,147 |
| 7 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 4,533,117 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
