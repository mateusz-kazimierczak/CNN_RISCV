# B1-standalone: B1 instruction profile

Full inference: **1,792,953,997 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `9a880237526864575d888bc39fc88a1d96c3c827c26c49cb303bdaf573a893fc`; ELF: `5445775f5503b3a6426456074d69ab41fb225f268f28724431cca6d1b1a42bf8`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 1,792,953,997 | -3,074,324,373 | 2.714670× |
| B1-project-kernels | 1,793,359,106 | 1,792,953,997 | -405,109 | 1.000226× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 50652 bytes (derived; allocated_executable_sections).
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
| 4 | rv64imc/pointwise_dot8_oc4/int8 | 118,477,195 |
| 1 | project/stem_rgb3x3/int8 | 90,810,140 |
| 58 | rv64imc/pointwise_dot8_oc4/int8 | 69,949,393 |
| 57 | rv64imc/pointwise_dot8_oc4/int8 | 61,673,619 |
| 11 | rv64imc/pointwise_dot8_oc4/int8 | 56,488,341 |
| 7 | rv64imc/pointwise_dot8_oc4/int8 | 56,263,065 |
| 36 | rv64imc/pointwise_dot8_oc4/int8 | 55,289,192 |
| 32 | rv64imc/pointwise_dot8_oc4/int8 | 55,289,181 |
| 40 | rv64imc/pointwise_dot8_oc4/int8 | 55,289,037 |
| 8 | rv64imc/depthwise_3x3/int8 | 54,548,776 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
