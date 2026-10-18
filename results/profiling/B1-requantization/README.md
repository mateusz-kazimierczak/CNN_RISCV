# B1-requantization: B1 instruction profile

Full inference: **1,694,945,564 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `416445553a26b5639e9014ba73047dc354a2609d208e09e7b3b6c77e2c230b5f`; ELF: `8c6c2f42c59a9827fd35a2b4c3b427dc9a1750090a390f99c0c47357cc59f19a`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 1,694,945,564 | -3,172,332,806 | 2.871643× |
| B1-readable | 1,792,953,997 | 1,694,945,564 | -98,008,433 | 1.057824× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 50712 bytes (derived; allocated_executable_sections).
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
| 4 | rv64imc/pointwise_dot8_oc4/int8 | 100,688,138 |
| 1 | project/stem_rgb3x3/int8 | 84,941,346 |
| 58 | rv64imc/pointwise_dot8_oc4/int8 | 69,066,916 |
| 57 | rv64imc/pointwise_dot8_oc4/int8 | 61,446,723 |
| 40 | rv64imc/pointwise_dot8_oc4/int8 | 53,424,657 |
| 36 | rv64imc/pointwise_dot8_oc4/int8 | 53,396,896 |
| 32 | rv64imc/pointwise_dot8_oc4/int8 | 53,388,490 |
| 34 | rv64imc/pointwise_dot8_oc4/int8 | 49,986,508 |
| 38 | rv64imc/pointwise_dot8_oc4/int8 | 49,986,508 |
| 11 | rv64imc/pointwise_dot8_oc4/int8 | 49,873,743 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
