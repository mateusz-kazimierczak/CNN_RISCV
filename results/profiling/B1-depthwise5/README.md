# B1-depthwise5: B1 instruction profile

Full inference: **2,069,251,680 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `a29dde566c5208af1edfb6a75ae53c8f21099273327deadd438f78b6c263ce27`; ELF: `c75b7f4435f32c703a51ced881519546d049c902f61a984cffeb731c5e9afa03`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 2,069,251,680 | -2,798,026,690 | 2.352193× |
| B1-oc4 | 2,215,157,070 | 2,069,251,680 | -145,905,390 | 1.070511× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 46160 bytes (derived; allocated_executable_sections).
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
| 8 | pinned_reference/depthwise_conv_2d/int8 | 125,589,275 |
| 4 | rv64imc/pointwise_dot8_oc4/int8 | 124,498,315 |
| 2 | pinned_reference/depthwise_conv_2d/int8 | 104,625,788 |
| 58 | rv64imc/pointwise_dot8_oc4/int8 | 70,262,993 |
| 5 | pinned_reference/depthwise_conv_2d/int8 | 64,107,723 |
| 57 | rv64imc/pointwise_dot8_oc4/int8 | 61,752,019 |
| 11 | rv64imc/pointwise_dot8_oc4/int8 | 58,746,261 |
| 7 | rv64imc/pointwise_dot8_oc4/int8 | 58,520,985 |
| 36 | rv64imc/pointwise_dot8_oc4/int8 | 55,947,752 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
