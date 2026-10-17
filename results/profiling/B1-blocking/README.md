# B1 pointwise output-channel blocking

**OC4 is selected by the measured instruction-count criterion.** It wins against both block one and OC2 on all 32 pointwise layers. No other execution unit changes its instruction count. Both alternatives retain the validated stem unrolling choice.

| Schedule | Full instructions | Change vs parent | Executable code | Code increase |
|---|---:|---:|---:|---:|
| OC1 | 2,577,746,525 | 0.00% | 24,600 bytes | +0 bytes |
| OC2 | 2,334,349,011 | -9.44% | 29,120 bytes | +4,520 bytes |
| OC4 | 2,215,157,070 | -14.07% | 38,336 bytes | +13,736 bytes |

The accepted build retires **2,215,157,070 instructions: 14.07% fewer than the B1 stem checkpoint and 54.49% fewer than LiteRT B0** (4,867,278,370). OC2 remains available when its 9,216-byte code saving relative to OC4 is preferred. No hardware cycle, cache or timing measurements are claimed.

| Representative unit | Parent OC1 | OC2 | OC4 | OC4 reduction vs parent |
|---|---:|---:|---:|---:|
| Node 4 | 148,281,741 | 132,024,717 | 124,498,315 | 16.04% |
| Node 58 | 91,258,271 | 77,303,069 | 70,262,993 | 23.01% |

Pointwise work falls from 1,696,880,402 to 1,334,290,947 instructions. All 32 pointwise units improve; the remaining 32 units, including stem and depthwise, retain exactly their previous counts. `nodes.csv` preserves every pointwise comparison, with scope, unit and evidence labels.

## Implementation

`pointwise_dot8_blocked` computes two or four output channels together. Each accumulator initializes from its own precomputed corrected bias and visits input channels in order. Within each eight-input group, `ScalarDot8Block` loads an activation once and reuses it across the independent accumulators. A static reduction-policy parameter separates the schedule from its arithmetic backend. This is still ordinary RV64IMC scalar arithmetic; no Xqmac instructions, packed loads, reduction-unroll-factor changes or weight repacking are enabled.

OHWI weights and reference per-channel double-rounding requantization are unchanged. The existing offline INT32 bound covers each corrected-bias accumulator and all prefixes. Physical tensor offsets, parameter fields and constant payloads are unchanged. Kernel contract identities and memory-plan hashes correctly change with the chosen implementation; there is no scratch or heap allocation. The observed canonical-input stack watermark remains 416 bytes and is not a universal bound.

All model pointwise output counts divide by four. Other graphs with nondivisible output counts retain the scalar block-one path, and reductions not supported by scalar dot8 retain the reference fallback. There is no unchecked partial block. Selected blocks are compiler-known evidence in each execution unit. Saved plans round-trip mixed per-unit choices; explicit conflicting flags, unsupported blocks and overrides of non-pointwise nodes are rejected before output files are written.

The later Xqmac backend can reuse the eight-lane grouping and output schedule, but must separately define and validate encoding, alignment, signed lane arithmetic and overflow semantics. Its preferred block size must be measured independently.

## Assembly and instruction mix

For node 58 (K=320), the measured RV64 disassembly has these steady-state reduction groups:

| Schedule | Products/group | Input byte loads | Weight byte loads | Multiply | Accumulator add | Pointer/branch | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| OC1 | 8 | 8 | 8 | 8 | 8 | 3 | 35 |
| OC2 | 16 | 8 | 16 | 16 | 16 | 3 | 59 |
| OC4 | 32 | 8 | 32 | 32 | 32 | 3 | 107 |

Neither blocked node-58 reduction loop contains stack accesses. OC4 does save/reload one outer-pixel value outside the hot reduction. Short K=16 is expanded by GCC; its complete unit count, including quantization and spills, is compared above. These are linked-assembly observations, not predictions from C++ source.

| Global category | Parent OC1 | OC2 | OC4 |
|---|---:|---:|---:|
| load | 790,764,403 | 621,495,671 | 536,955,238 |
| store | 9,277,731 | 9,277,735 | 9,310,224 |
| integer_alu | 1,182,847,355 | 1,131,892,041 | 1,108,794,780 |
| multiply | 388,650,126 | 388,650,126 | 388,650,126 |
| conditional_branch | 192,338,678 | 169,165,206 | 157,578,470 |
| jump | 13,868,232 | 13,868,232 | 13,868,232 |
| custom | 0 | 0 | 0 |

The global multiply count is unchanged. Useful executed products remain 381,239,488; logical graph MACs remain 385,187,552. Useful work is derived from the selected dense algorithm, not inferred from multiply opcodes. Loads decrease by 253,809,165; stores increase by 32,493. The store increase is reported even though the total instruction count improves.

## Footprint and evidence

Both schedules retain 4,916,136 bytes of actual read-only sections, 4,915,488 bytes of planned constants/parameters, a 1,505,280-byte activation arena and 1,505,424 bytes of BSS. OC4 costs 13,736 additional code bytes over the parent; OC2 costs 4,520. GCC analysis for each candidate rebuilds all five executable translation units with nine diagnostic stages and requires identical loaded bytes.

### B1-oc2

- Capture: `a7a1f11702e4e89e92e2a75d3201dd82f009c1722ea9b46c4619fd3af9a43811` under `build/profiling/compiler/`.
- ELF: `9163bb11c19bc357f87db4a22cd5c174c5100b2cd1d090774484b1022941f75b`.
- Replay: `a316899557b3ed1864c701cdcb45b8f348b4e8c23469241578a079b26438b2da` under `build/compiler/B1-oc2-replay/`: nodes 4/58 on all eight cases, plus two existing reference scalar-dot fixtures. Microbenchmarks remain separate from blocked-kernel results.
- Fixture pack SHA-256: `d70021e5b888381e11991ece0020310015678527e4e596056c8e5eabe8aefc00`.
- GCC analysis: `6694719c01a1e528f7da8bbf5f926be9138018e6d2e9c0d2ddafa7974aae6340` under `build/compiler/B1-oc2-gcc/`.

### B1-oc4

- Capture: `482d18bbff4c7df63fe41c90ca8d30d81b53807816528eeb13da6eb30038e41f` under `build/profiling/compiler/`.
- ELF: `825f1f1aeb2b7e90a3b2c239f3110c243aec48a0a41ee011609e1a74cd84bdf1`.
- Replay: `68b9f32142d9f4cbc70f18a0cf184ce5947ce777eb53576d15b4ffea183e6623` under `build/compiler/B1-oc4-replay/`: nodes 4/58 on all eight cases, plus two existing reference scalar-dot fixtures. Microbenchmarks remain separate from blocked-kernel results.
- Fixture pack SHA-256: `d70021e5b888381e11991ece0020310015678527e4e596056c8e5eabe8aefc00`.
- GCC analysis: `3e6204d2b3562ad04e5e229698fa10883db19dd90143d2cbffdaf6d15160e593` under `build/compiler/B1-oc4-gcc/`.

Both full profiles are repeated with identical event/PC captures, complete 1,000-byte public-output comparisons, all 64 units and 84 overhead instructions reconciled, and a common parent capture (`62c8e308b8ffd071a3db39d21f6bfaea54cdfaa328e3577896d1e547fdd19964`). Native release and native/sanitized diagnostic builds additionally cover all eight oracle cases; each diagnostic build compares 510 complete intermediate arrays.

The all-131 full input retains its known Softmax error at node 62 without exposing an output. Successful isolated node-4/node-58 replay on that input does not turn the full-model failure into a performance result.

## Reproduction

```sh
gmake compiler-b1-blocking-checkpoint  # selected OC4, complete correctness + repeated profiling
gmake compiler-b1-oc2-checkpoint      # independent smaller-code candidate
```

Use `--config B1 --stem-unroll --pointwise-block 2|4` with an explicit output directory for direct generation. The checkpoint recipes write separate `build/compiler/B1-oc2/` and `B1-oc4/` builds, retain `-O2`, and compare against the same stem parent. `B1_OC_PARENT_CAPTURE` overrides its location when restoring ignored captures on another machine. Default B1 retains block one.

The accepted viewer bundle is `build/explorer/B1-oc4.zip`, exported with the OC4 capture and matching GCC analysis. Its browser test checks the block-four selection, scalar backend, generated source and measured total. Weights are omitted from default viewer archives. Commands, actual dependency bytes, graph/prepared/kernel/memory plans and ELF identities are preserved in each immutable build snapshot.

No commit was requested for this optimization. This checkpoint stops before depthwise kernels or custom ISA work.
