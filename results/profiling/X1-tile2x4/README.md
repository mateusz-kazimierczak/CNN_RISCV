# X1-tile2x4: X1 instruction profile

Full inference: **594,975,670 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `48d6af2695dc7d80bab4c5ecb5c4ef0caa900ca47e8467a7112609f87d74bf1d`; ELF: `f271a3d9d4726824e395b3f728b608026f74d42c988253252a4cbe671d5f0e5c`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 594,975,670 | -4,272,302,700 | 8.180634× |
| X1-acc64 | 624,684,209 | 594,975,670 | -29,708,539 | 1.049932× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 49212 bytes (derived; allocated_executable_sections).
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
| 1 | project/stem_rgb3x3/int8 | 78,960,244 |
| 8 | rv64imc/depthwise_3x3/int8 | 38,351,741 |
| 15 | rv64imc/depthwise_5x5/int8 | 35,403,916 |
| 2 | rv64imc/depthwise_3x3/int8 | 33,768,853 |
| 4 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 32,310,815 |
| 37 | rv64imc/depthwise_5x5/int8 | 29,558,136 |
| 33 | rv64imc/depthwise_5x5/int8 | 29,552,500 |
| 5 | rv64imc/depthwise_3x3/int8 | 24,034,341 |
| 30 | rv64imc/depthwise_5x5/int8 | 21,057,212 |
| 12 | rv64imc/depthwise_5x5/int8 | 19,826,738 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
