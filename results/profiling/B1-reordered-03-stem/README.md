# B1-reordered-03-stem: B1 instruction profile

Full inference: **2,237,440,941 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `e19373e46ae62cd49016beb012f6e07e45d30152e3c4b3a6c98411971403bf59`; ELF: `fc461a1ca6753fd04d1f5d8a2d7f93b84a47f52b93e4b8d6a6687e1265c232ef`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 2,237,440,941 | -2,629,837,429 | 2.175377× |
| B1-reordered-02-depthwise | 2,388,006,921 | 2,237,440,941 | -150,565,980 | 1.067294× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 37344 bytes (derived; allocated_executable_sections).
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
| 58 | rv64imc/pointwise_dot8/int8 | 91,258,271 |
| 57 | rv64imc/pointwise_dot8/int8 | 79,866,194 |
| 40 | rv64imc/pointwise_dot8/int8 | 71,785,378 |
| 36 | rv64imc/pointwise_dot8/int8 | 71,785,143 |
| 32 | rv64imc/pointwise_dot8/int8 | 71,785,132 |
| 11 | rv64imc/pointwise_dot8/int8 | 71,390,615 |
| 7 | rv64imc/pointwise_dot8/int8 | 71,384,859 |
| 34 | rv64imc/pointwise_dot8/int8 | 65,693,311 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
