# X2-optimized: X2 instruction profile

Full inference: **436,158,109 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `7f3f4938613c6b9fe38dbd586c10bbd897190c9e4e9ba6eef291f7fd2119e5fb`; ELF: `585fdb35d053c13a63806b6236b7402f629f0739e872ebfa245a41d926d46f42`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 436,158,109 | -4,431,120,261 | 11.159436× |
| X2 | 458,701,498 | 436,158,109 | -22,543,389 | 1.051686× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 31968 bytes (derived; allocated_executable_sections).
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
| 15 | rv64imc/depthwise_5x5/int8 | 31,298,687 |
| 8 | rv64imc/depthwise_3x3/int8 | 28,002,341 |
| 2 | rv64imc/depthwise_3x3/int8 | 24,565,009 |
| 33 | rv64imc/depthwise_5x5/int8 | 24,308,261 |
| 37 | rv64imc/depthwise_5x5/int8 | 24,308,261 |
| 5 | rv64imc/depthwise_3x3/int8 | 17,883,656 |
| 30 | rv64imc/depthwise_5x5/int8 | 17,437,583 |
| 12 | rv64imc/depthwise_5x5/int8 | 17,393,948 |
| 44 | rv64imc/depthwise_5x5/int8 | 11,594,130 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
