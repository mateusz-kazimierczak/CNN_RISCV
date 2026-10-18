# B1-spatial2-oc2-shared: B1 instruction profile

Full inference: **1,598,070,860 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `5091b2deec835bc4538b0a05d0d2ef2f93d73318a5e4031d3052342e6d1a2cda`; ELF: `ec0ea1c39df7e56cde2245f9f3d5f5026b410995d08bc076862ff249c8758544`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 1,598,070,860 | -3,269,207,510 | 3.045721× |
| B1-requantization-selected | 1,650,025,771 | 1,598,070,860 | -51,954,911 | 1.032511× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 51388 bytes (derived; allocated_executable_sections).
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
| 4 | rv64imc/pointwise_dot8_spatial2_oc2/int8 | 102,544,669 |
| 1 | project/stem_rgb3x3/int8 | 78,960,244 |
| 58 | rv64imc/pointwise_dot8_spatial2_oc2/int8 | 64,647,249 |
| 57 | rv64imc/pointwise_dot8_spatial2_oc2/int8 | 56,670,211 |
| 40 | rv64imc/pointwise_dot8_spatial2_oc2/int8 | 50,394,515 |
| 36 | rv64imc/pointwise_dot8_spatial2_oc2/int8 | 50,366,363 |
| 32 | rv64imc/pointwise_dot8_spatial2_oc2/int8 | 50,357,957 |
| 7 | rv64imc/pointwise_dot8_spatial2_oc2/int8 | 49,793,891 |
| 11 | rv64imc/pointwise_dot8_spatial2_oc2/int8 | 49,774,978 |
| 34 | rv64imc/pointwise_dot8_spatial2_oc2/int8 | 46,436,670 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
