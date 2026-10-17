# B1-stem-unroll: B1 instruction profile

Full inference: **2,577,746,525 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `62c8e308b8ffd071a3db39d21f6bfaea54cdfaa328e3577896d1e547fdd19964`; ELF: `03d836651e16c59160f26287a1f1ac1be991ecfc8ff11bfd53fe7afcafe77e71`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 2,577,746,525 | -2,289,531,845 | 1.888191× |
| B1-pointwise | 2,728,312,505 | 2,577,746,525 | -150,565,980 | 1.058410× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 24600 bytes (derived; allocated_executable_sections).
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
| 4 | rv64imc/pointwise_dot8/int8 | 148,281,741 |
| 1 | pinned_reference/conv_2d/int8 | 126,483,738 |
| 8 | pinned_reference/depthwise_conv_2d/int8 | 125,589,275 |
| 2 | pinned_reference/depthwise_conv_2d/int8 | 104,625,788 |
| 58 | rv64imc/pointwise_dot8/int8 | 91,258,271 |
| 57 | rv64imc/pointwise_dot8/int8 | 79,866,194 |
| 15 | pinned_reference/depthwise_conv_2d/int8 | 75,625,351 |
| 40 | rv64imc/pointwise_dot8/int8 | 71,785,378 |
| 36 | rv64imc/pointwise_dot8/int8 | 71,785,143 |
| 32 | rv64imc/pointwise_dot8/int8 | 71,785,132 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
