# B1-spatial2-oc4-shared: B1 instruction profile

Full inference: **1,797,765,968 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `4490aa016e632763d8c71125e918c4ecaf8f41316a8b12403b170219f4681e5e`; ELF: `e0ceb29dba008215f5f64b8bbe10bcfa489cdd06f079a2a0a86d7288c296dffc`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 1,797,765,968 | -3,069,512,402 | 2.707404× |
| B1-requantization-selected | 1,650,025,771 | 1,797,765,968 | +147,740,197 | 0.917820× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 68764 bytes (derived; allocated_executable_sections).
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
| 4 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 114,141,600 |
| 1 | project/stem_rgb3x3/int8 | 78,960,244 |
| 58 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 76,152,286 |
| 57 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 68,168,736 |
| 40 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 59,054,875 |
| 36 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 59,026,723 |
| 32 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 59,018,317 |
| 7 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 55,946,724 |
| 11 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 55,927,811 |
| 34 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 55,170,528 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
