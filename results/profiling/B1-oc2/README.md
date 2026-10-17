# B1-oc2: B1 instruction profile

Full inference: **2,334,349,011 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `a7a1f11702e4e89e92e2a75d3201dd82f009c1722ea9b46c4619fd3af9a43811`; ELF: `9163bb11c19bc357f87db4a22cd5c174c5100b2cd1d090774484b1022941f75b`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 2,334,349,011 | -2,532,929,359 | 2.085069× |
| B1-stem-unroll | 2,577,746,525 | 2,334,349,011 | -243,397,514 | 1.104268× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 29120 bytes (derived; allocated_executable_sections).
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
| 4 | rv64imc/pointwise_dot8_oc2/int8 | 132,024,717 |
| 1 | pinned_reference/conv_2d/int8 | 126,483,738 |
| 8 | pinned_reference/depthwise_conv_2d/int8 | 125,589,275 |
| 2 | pinned_reference/depthwise_conv_2d/int8 | 104,625,788 |
| 58 | rv64imc/pointwise_dot8_oc2/int8 | 77,303,069 |
| 15 | pinned_reference/depthwise_conv_2d/int8 | 75,625,351 |
| 57 | rv64imc/pointwise_dot8_oc2/int8 | 67,408,434 |
| 5 | pinned_reference/depthwise_conv_2d/int8 | 64,107,723 |
| 11 | rv64imc/pointwise_dot8_oc2/int8 | 62,810,519 |
| 7 | rv64imc/pointwise_dot8_oc2/int8 | 62,804,763 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
