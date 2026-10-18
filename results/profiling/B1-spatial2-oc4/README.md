# B1-spatial2-oc4: B1 instruction profile

Full inference: **1,775,982,033 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `2f7e130274edffa7d5b1b7cf93bd82e4985f8ed34b7458e03f78247257cc9a6e`; ELF: `61c8a264db2f8649c49ef72b22497dcb075eff7bbcfb7888452071bb79c49908`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 1,775,982,033 | -3,091,296,337 | 2.740612× |
| B1-requantization-selected | 1,650,025,771 | 1,775,982,033 | +125,956,262 | 0.929078× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 71092 bytes (derived; allocated_executable_sections).
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
| 4 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 105,097,371 |
| 1 | project/stem_rgb3x3/int8 | 78,960,244 |
| 58 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 76,152,286 |
| 57 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 68,168,736 |
| 40 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 59,054,875 |
| 36 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 59,026,723 |
| 32 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 59,018,317 |
| 34 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 55,170,528 |
| 38 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 55,170,528 |
| 7 | rv64imc/pointwise_dot8_spatial2_oc4/int8 | 52,838,949 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
