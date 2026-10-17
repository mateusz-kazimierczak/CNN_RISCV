# A0-stage4-profile: A0 instruction profile

Full inference: **6,063,975,187 retired instructions**. Allocation is absent.
Execution units: 64; invocation overhead: 85 instructions.
Two event/PC captures match exactly; all 1,000 output bytes match the reference.

Capture: `e50bda81de148de9d6dd8273bb8fbe15effae6679be1a9788288f957a1e32aad`; ELF: `ad7135f142507b3e727e61bca4b0e8dc27eff8c4e6df5c6e85aa940b103f604e`.

## Comparisons

| Reference | Before | After | Change | Instruction-count ratio |
|---|---:|---:|---:|---:|
| B0 | 4,867,278,370 | 6,063,975,187 | +1,196,696,817 | 0.802655× |
| A0-stage4-profile | 6,063,975,187 | 6,063,975,187 | +0 | 1.000000× |

Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.

## Footprint

- executable_code: 48688 bytes (derived; allocated_executable_sections).
- readonly: 4870088 bytes (derived; allocated_readonly_sections).
- bss: 1505424 bytes (derived; allocated_nobits_sections).
- initialized_writable: 20 bytes (derived; allocated_writable_sections).
- activation_scratch_workspace: 1505280 bytes (derived; static_memory_plan).
- planned_constants_and_parameters: 4867424 bytes (derived; static_memory_plan).
- peak_live_activations: 1505280 bytes (derived; static_memory_plan).
- hardware_cycles: None cycles (unavailable; CV-Wally).

## Largest inclusive execution units

| Node(s) | Implementation | Instructions |
|---|---|---:|
| 4 | pinned_reference/conv_2d/int8 | 398,850,865 |
| 1 | pinned_reference/conv_2d/int8 | 281,448,170 |
| 58 | pinned_reference/conv_2d/int8 | 249,752,376 |
| 57 | pinned_reference/conv_2d/int8 | 218,932,878 |
| 40 | pinned_reference/conv_2d/int8 | 195,727,624 |
| 36 | pinned_reference/conv_2d/int8 | 195,727,388 |
| 32 | pinned_reference/conv_2d/int8 | 195,727,377 |
| 11 | pinned_reference/conv_2d/int8 | 192,890,211 |
| 7 | pinned_reference/conv_2d/int8 | 192,884,454 |
| 34 | pinned_reference/conv_2d/int8 | 180,065,268 |

## Limits

- Spike retirements are not CV-Wally cycles.
- Memory instructions are not DRAM traffic or cache misses.
- AOT workspace and LiteRT total arena have different accounting.
- Softmax domain preflight and existing wrapper costs remain inside inference.
- Known all-zero-point input fails Softmax; canonical performance input is seed 1.
