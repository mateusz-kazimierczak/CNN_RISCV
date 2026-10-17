# B1-depthwise: B1 instruction profile

Full inference: **1,874,851,486 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `228637b6b0a191eb384c8e6ebb62dc56fb887780a6177e2e1dbd3efde5ba9760`; ELF: `30987a4a2a400e386a5819b9498c82b448d4da46c84e93b20131b1e4216a4068`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 1,874,851,486 | -2,992,426,884 | 2.596087× |
| B1-oc4 | 2,215,157,070 | 1,874,851,486 | -340,305,584 | 1.181511× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 51072 bytes (derived; allocated_executable_sections).
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
| 4 | rv64imc/pointwise_dot8_oc4/int8 | 124,498,315 |
| 58 | rv64imc/pointwise_dot8_oc4/int8 | 70,262,993 |
| 57 | rv64imc/pointwise_dot8_oc4/int8 | 61,752,019 |
| 11 | rv64imc/pointwise_dot8_oc4/int8 | 58,746,261 |
| 7 | rv64imc/pointwise_dot8_oc4/int8 | 58,520,985 |
| 8 | rv64imc/depthwise_3x3/int8 | 56,806,696 |
| 36 | rv64imc/pointwise_dot8_oc4/int8 | 55,947,752 |
| 32 | rv64imc/pointwise_dot8_oc4/int8 | 55,947,741 |
| 40 | rv64imc/pointwise_dot8_oc4/int8 | 55,947,597 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
