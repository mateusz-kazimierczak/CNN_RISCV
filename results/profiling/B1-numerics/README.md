# B1-numerics: B1 instruction profile

Full inference: **1,843,170,046 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `1abb9c425edb7649cd5cc9d9b64831a6ae4847fc199a9684da0f5c32f037aab3`; ELF: `3813b31972aa76f9c923ac4f589a38eef59eb3f812cabf703175dafdae4fcebe`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 1,843,170,046 | -3,024,108,324 | 2.640710× |
| B1-depthwise | 1,874,851,486 | 1,843,170,046 | -31,681,440 | 1.017189× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 51188 bytes (derived; allocated_executable_sections).
- readonly: 4916136 bytes (derived; allocated_readonly_sections).
- bss: 1505424 bytes (derived; allocated_nobits_sections).
- initialized_writable: 20 bytes (derived; allocated_writable_sections).
- activation_scratch_workspace: 1505280 bytes (derived; static_memory_plan).
- planned_constants_and_parameters: 4915488 bytes (derived; static_memory_plan).
- peak_live_activations: 1505280 bytes (derived; static_memory_plan).
- hardware_cycles: None cycles (unavailable; CV-Wally).

## Largest inclusive execution units

| Node(s) | Implementation | Instructions |
|---|---|---:|
| 1 | pinned_reference/conv_2d/int8 | 126,483,738 |
| 4 | rv64imc/pointwise_dot8_oc4/int8 | 118,477,195 |
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
