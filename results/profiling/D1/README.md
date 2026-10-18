# D1: X3 instruction profile

Full inference: **389,566,544 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `7842871e8857a37f817e42cf1f3c24fcdc26ce2e114a07d0c133eedc135bbff7`; ELF: `cccf970c048fb6b61653c81dd6d36d4dbe59923c20c4234fd6cd3cfde46f4ec7`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 389,566,544 | -4,477,711,826 | 12.494087× |
| X3-selected | 423,520,020 | 389,566,544 | -33,953,476 | 1.087157× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 31932 bytes (derived; allocated_executable_sections).
- readonly: 5672536 bytes (derived; allocated_readonly_sections).
- bss: 1505424 bytes (derived; allocated_nobits_sections).
- initialized_writable: 20 bytes (derived; allocated_writable_sections).
- activation_scratch_workspace: 1505280 bytes (derived; static_memory_plan).
- planned_constants_and_parameters: 5672040 bytes (derived; static_memory_plan).
- peak_live_activations: 1505280 bytes (derived; static_memory_plan).
- hardware_cycles: None cycles (unavailable; CV-Wally).

## Largest inclusive execution units

| Node(s) | Implementation | Instructions |
|---|---|---:|
| 1 | project/stem_rgb3x3/int8 | 69,472,265 |
| 15 | rv64imc/depthwise_5x5/int8 | 26,791,246 |
| 8 | rv64imc/depthwise_3x3/int8 | 22,947,452 |
| 33 | rv64imc/depthwise_5x5/int8 | 21,164,848 |
| 37 | rv64imc/depthwise_5x5/int8 | 21,164,848 |
| 2 | rv64imc/depthwise_3x3/int8 | 20,359,636 |
| 30 | rv64imc/depthwise_5x5/int8 | 15,465,472 |
| 12 | rv64imc/depthwise_5x5/int8 | 14,686,349 |
| 5 | rv64imc/depthwise_3x3/int8 | 14,554,404 |
| 44 | rv64imc/depthwise_5x5/int8 | 10,338,868 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
