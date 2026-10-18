# X3-selected: X3 instruction profile

Full inference: **423,520,020 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `e988e5a7030bf21f78d33af39706e193ed26996d47bed5414c173785ef3e67c1`; ELF: `638d7096b8fce3fffddf041c778a9d23635db22aaf90fea4150dee2be495b8c0`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 423,520,020 | -4,443,758,350 | 11.492440× |
| X2-optimized | 436,158,109 | 423,520,020 | -12,638,089 | 1.029841× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 32020 bytes (derived; allocated_executable_sections).
- readonly: 4916216 bytes (derived; allocated_readonly_sections).
- bss: 1505424 bytes (derived; allocated_nobits_sections).
- initialized_writable: 20 bytes (derived; allocated_writable_sections).
- activation_scratch_workspace: 1505280 bytes (derived; static_memory_plan).
- planned_constants_and_parameters: 4915720 bytes (derived; static_memory_plan).
- peak_live_activations: 1505280 bytes (derived; static_memory_plan).
- hardware_cycles: None cycles (unavailable; CV-Wally).

## Largest inclusive execution units

| Node(s) | Implementation | Instructions |
|---|---|---:|
| 1 | project/stem_rgb3x3/int8 | 69,472,265 |
| 15 | rv64imc/depthwise_5x5/int8 | 31,298,687 |
| 8 | rv64imc/depthwise_3x3/int8 | 27,425,221 |
| 33 | rv64imc/depthwise_5x5/int8 | 24,308,261 |
| 37 | rv64imc/depthwise_5x5/int8 | 24,308,261 |
| 2 | rv64imc/depthwise_3x3/int8 | 24,261,453 |
| 30 | rv64imc/depthwise_5x5/int8 | 17,437,583 |
| 12 | rv64imc/depthwise_5x5/int8 | 17,393,948 |
| 5 | rv64imc/depthwise_3x3/int8 | 17,248,541 |
| 44 | rv64imc/depthwise_5x5/int8 | 11,594,130 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
