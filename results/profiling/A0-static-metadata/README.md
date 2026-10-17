# A0-static-metadata: A0 instruction profile

Full inference: **3,980,184,493 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 84 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `be93754b9e78bd63475c266fe05bea45f80541d015b081eb264cdb3534c6b5fd`; ELF: `f44380f9d25886f511bfae3f4ece65acfb830b7141ec54dc1d761c06dee31039`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 3,980,184,493 | -887,093,877 | 1.222878× |
| A0-stage4-profile | 6,063,975,187 | 3,980,184,493 | -2,083,790,694 | 1.523541× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 23240 bytes (derived; allocated_executable_sections).
- readonly: 4868072 bytes (derived; allocated_readonly_sections).
- bss: 1505424 bytes (derived; allocated_nobits_sections).
- initialized_writable: 20 bytes (derived; allocated_writable_sections).
- activation_scratch_workspace: 1505280 bytes (derived; static_memory_plan).
- planned_constants_and_parameters: 4867424 bytes (derived; static_memory_plan).
- peak_live_activations: 1505280 bytes (derived; static_memory_plan).
- hardware_cycles: None cycles (unavailable; CV-Wally).

## Largest inclusive execution units

| Node(s) | Implementation | Instructions |
|---|---|---:|
| 1 | pinned_reference/conv_2d/int8 | 277,049,718 |
| 4 | pinned_reference/conv_2d/int8 | 228,990,399 |
| 58 | pinned_reference/conv_2d/int8 | 164,703,520 |
| 57 | pinned_reference/conv_2d/int8 | 145,549,855 |
| 40 | pinned_reference/conv_2d/int8 | 127,236,482 |
| 36 | pinned_reference/conv_2d/int8 | 127,236,246 |
| 32 | pinned_reference/conv_2d/int8 | 127,236,235 |
| 8 | pinned_reference/depthwise_conv_2d/int8 | 125,589,275 |
| 34 | pinned_reference/conv_2d/int8 | 119,432,561 |
| 38 | pinned_reference/conv_2d/int8 | 119,431,943 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
