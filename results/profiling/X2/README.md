# X2: X2 instruction profile

Full inference: **458,701,498 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `1f04302f3bd8362f711fa77acceafcc13c9e34946539e3dd8878639deb81cf64`; ELF: `e9dffe32b3ff131da8c3ed5f5ca0a75c75d120a5f849a0ff2bf1f466c8075613`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 458,701,498 | -4,408,576,872 | 10.610993× |
| X1-tile2x4 | 594,975,670 | 458,701,498 | -136,274,172 | 1.297087× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 33004 bytes (derived; allocated_executable_sections).
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
| 33 | rv64imc/depthwise_5x5/int8 | 32,621,022 |
| 37 | rv64imc/depthwise_5x5/int8 | 32,621,022 |
| 15 | rv64imc/depthwise_5x5/int8 | 31,298,687 |
| 8 | rv64imc/depthwise_3x3/int8 | 29,421,252 |
| 2 | rv64imc/depthwise_3x3/int8 | 26,731,600 |
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
