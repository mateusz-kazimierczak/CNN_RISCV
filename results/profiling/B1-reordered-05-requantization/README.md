# B1-reordered-05-requantization: B1 instruction profile

Full inference: **2,009,370,040 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `e5feabb2b8246cd10dba6f4ffa13fe7aebb233b812614301bc03a6ff8b16857c`; ELF: `0e82a732cd19dff7202053fe5abbd81cd0ad14cc257bd52490c8ebfdcc744e99`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 2,009,370,040 | -2,857,908,330 | 2.422291× |
| B1-reordered-04-runtime | 2,155,543,452 | 2,009,370,040 | -146,173,412 | 1.072746× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 39316 bytes (derived; allocated_executable_sections).
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
| 4 | rv64imc/pointwise_dot8/int8 | 119,654,668 |
| 58 | rv64imc/pointwise_dot8/int8 | 90,062,194 |
| 57 | rv64imc/pointwise_dot8/int8 | 79,560,898 |
| 1 | project/stem_rgb3x3/int8 | 78,960,244 |
| 40 | rv64imc/pointwise_dot8/int8 | 69,262,438 |
| 36 | rv64imc/pointwise_dot8/int8 | 69,234,287 |
| 32 | rv64imc/pointwise_dot8/int8 | 69,225,881 |
| 34 | rv64imc/pointwise_dot8/int8 | 65,265,100 |
| 38 | rv64imc/pointwise_dot8/int8 | 65,265,100 |
| 7 | rv64imc/pointwise_dot8/int8 | 60,730,675 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
