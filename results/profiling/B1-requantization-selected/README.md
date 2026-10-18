# B1-requantization-selected: B1 instruction profile

Full inference: **1,650,025,771 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `36c3ac40b6ebb1bb8985b0c6990e88b48def27f0ce5af60faa0a6099aca2d291`; ELF: `2bd4ec9083ea15912fb2accafd926876d237088aacb231250990f3803c41ac1a`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 1,650,025,771 | -3,217,252,599 | 2.949820× |
| B1-readable | 1,792,953,997 | 1,650,025,771 | -142,928,226 | 1.086622× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 54520 bytes (derived; allocated_executable_sections).
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
| 4 | rv64imc/pointwise_dot8_oc4/int8 | 97,978,634 |
| 1 | project/stem_rgb3x3/int8 | 78,960,244 |
| 58 | rv64imc/pointwise_dot8_oc4/int8 | 69,066,916 |
| 57 | rv64imc/pointwise_dot8_oc4/int8 | 61,446,723 |
| 40 | rv64imc/pointwise_dot8_oc4/int8 | 53,424,657 |
| 36 | rv64imc/pointwise_dot8_oc4/int8 | 53,396,896 |
| 32 | rv64imc/pointwise_dot8_oc4/int8 | 53,388,490 |
| 34 | rv64imc/pointwise_dot8_oc4/int8 | 49,986,508 |
| 38 | rv64imc/pointwise_dot8_oc4/int8 | 49,986,508 |
| 7 | rv64imc/pointwise_dot8_oc4/int8 | 47,873,076 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
