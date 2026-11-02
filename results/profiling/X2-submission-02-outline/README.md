# X2-submission-02-outline: X2 instruction profile

Full inference: **436,487,389 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `22c581cbd67f9665e0749ba79ecdf69c6d8e3d9419e1079d95d201fb7ae61631`; ELF: `36748db940b135cbc9b3be588c70859048584a81145a624b437bff96d9d5397b`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 436,487,389 | -4,430,790,981 | 11.151017× |
| X2 | 458,701,498 | 436,487,389 | -22,214,109 | 1.050893× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 32052 bytes (derived; allocated_executable_sections).
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
