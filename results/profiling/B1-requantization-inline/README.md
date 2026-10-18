# B1-requantization-inline: B1 instruction profile

Full inference: **1,671,976,400 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `5987138446d35db94636b56354544f6bd6c780f68d60b329360773e2905730ec`; ELF: `0cced4586d318d03a6615211ca992834b6e707e842a19ebf2d1807cbe14eb694`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 1,671,976,400 | -3,195,301,970 | 2.911093× |
| B1-readable | 1,792,953,997 | 1,671,976,400 | -120,977,597 | 1.072356× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 58132 bytes (derived; allocated_executable_sections).
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
| 58 | rv64imc/pointwise_dot8_oc4/int8 | 69,490,179 |
| 57 | rv64imc/pointwise_dot8_oc4/int8 | 61,944,663 |
| 40 | rv64imc/pointwise_dot8_oc4/int8 | 53,457,584 |
| 36 | rv64imc/pointwise_dot8_oc4/int8 | 53,429,433 |
| 32 | rv64imc/pointwise_dot8_oc4/int8 | 53,421,027 |
| 34 | rv64imc/pointwise_dot8_oc4/int8 | 50,343,816 |
| 38 | rv64imc/pointwise_dot8_oc4/int8 | 50,343,816 |
| 7 | rv64imc/pointwise_dot8_oc4/int8 | 47,873,076 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
