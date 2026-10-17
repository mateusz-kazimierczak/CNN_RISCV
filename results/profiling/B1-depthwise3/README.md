# B1-depthwise3: B1 instruction profile

Full inference: **2,020,756,876 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `b1b1b2ef7e6641ebb2c86e1889623d162a3cbe33143412e6d63648a63b76d605`; ELF: `9dabb5b25d62469d88efbd4cb6080fed4707ab4039e8c0521f499b24d46bcbd3`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 2,020,756,876 | -2,846,521,494 | 2.408641× |
| B1-oc4 | 2,215,157,070 | 2,020,756,876 | -194,400,194 | 1.096202× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 43252 bytes (derived; allocated_executable_sections).
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
| 15 | pinned_reference/depthwise_conv_2d/int8 | 75,625,351 |
| 58 | rv64imc/pointwise_dot8_oc4/int8 | 70,262,993 |
| 57 | rv64imc/pointwise_dot8_oc4/int8 | 61,752,019 |
| 11 | rv64imc/pointwise_dot8_oc4/int8 | 58,746,261 |
| 12 | pinned_reference/depthwise_conv_2d/int8 | 58,712,426 |
| 7 | rv64imc/pointwise_dot8_oc4/int8 | 58,520,985 |
| 8 | rv64imc/depthwise_3x3/int8 | 56,806,696 |
| 36 | rv64imc/pointwise_dot8_oc4/int8 | 55,947,752 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
