# B1-reordered-04-runtime: B1 instruction profile

Full inference: **2,155,543,452 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `98c879abf496b9f6e5eb472d31aaa31051bff70ea5be29a533190f45e1b5e2a8`; ELF: `96edc13a39b0893ad975ba06c58d5313055f0e66c4053930c1c999dce2e3e8d7`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 2,155,543,452 | -2,711,734,918 | 2.258028× |
| B1-reordered-03-stem | 2,237,440,941 | 2,155,543,452 | -81,897,489 | 1.037994× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 36924 bytes (derived; allocated_executable_sections).
- readonly: 4915984 bytes (derived; allocated_readonly_sections).
- bss: 1505424 bytes (derived; allocated_nobits_sections).
- initialized_writable: 20 bytes (derived; allocated_writable_sections).
- activation_scratch_workspace: 1505280 bytes (derived; static_memory_plan).
- planned_constants_and_parameters: 4915488 bytes (derived; static_memory_plan).
- peak_live_activations: 1505280 bytes (derived; static_memory_plan).
- hardware_cycles: None cycles (unavailable; CV-Wally).

## Largest inclusive execution units

| Node(s) | Implementation | Instructions |
|---|---|---:|
| 4 | rv64imc/pointwise_dot8/int8 | 142,260,621 |
| 58 | rv64imc/pointwise_dot8/int8 | 90,944,671 |
| 1 | project/stem_rgb3x3/int8 | 90,810,140 |
| 57 | rv64imc/pointwise_dot8/int8 | 79,787,794 |
| 40 | rv64imc/pointwise_dot8/int8 | 71,126,818 |
| 36 | rv64imc/pointwise_dot8/int8 | 71,126,583 |
| 32 | rv64imc/pointwise_dot8/int8 | 71,126,572 |
| 11 | rv64imc/pointwise_dot8/int8 | 69,132,695 |
| 7 | rv64imc/pointwise_dot8/int8 | 69,126,939 |
| 34 | rv64imc/pointwise_dot8/int8 | 65,583,551 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
