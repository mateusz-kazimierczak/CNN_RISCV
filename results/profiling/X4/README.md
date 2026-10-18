# X4: X4 instruction profile

Full inference: **229,114,977 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `94ce4612237aa113e5e42baed7a7b2211a9f76adad4977fafb02b85051c10a7b`; ELF: `81efdf6e7f268559a881c5f20a5c307f30fd983d050980f355f8236fccd03b2a`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 229,114,977 | -4,638,163,393 | 21.243825× |
| X3-selected | 423,520,020 | 229,114,977 | -194,405,043 | 1.848504× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 38572 bytes (derived; allocated_executable_sections).
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
| 4 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 9,853,341 |
| 8 | rv64imc/depthwise_3x3/int8 | 8,394,233 |
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
