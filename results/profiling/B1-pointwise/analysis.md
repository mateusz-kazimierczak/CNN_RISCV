# First B1 scalar pointwise checkpoint

The 32 pointwise convolutions were 74.1% of A0 retirements. This checkpoint replaces them with a software-only scalar kernel; every other unit retains exactly its previous instruction count. All 32 selected units improve; no unit regresses.

| Scope | A0 instructions | B1 instructions | Reduction |
|---|---:|---:|---:|
| Full inference | 3,980,184,493 | 2,728,312,505 | 31.45% |
| All pointwise kernels | 2,948,752,390 | 1,696,880,402 | 42.45% |
| Node 4, K=16 | 228,990,399 | 148,281,741 | 35.25% |
| Node 58, K=320 | 164,703,520 | 91,258,271 | 44.59% |
| Stem (unchanged) | 277,049,718 | 277,049,718 | 0.00% |

B0 retires 4,867,278,370 instructions: this checkpoint is **43.95% lower**. These are retirement counts, not cycle or wall-clock speedups. Useful executed products remain 381,239,488; logical graph MACs remain 385,187,552.

## Implementation and compiled evidence

`kernels/rv64imc/pointwise.h` replaces the spatially general convolution loop with pointer-based dense rows. Offline corrected biases remove input-zero-point additions from the reduction. The scalar `dot8` groups eight sequential signed INT8 products; it retains the pinned double-rounding requantization helper. No packed loads, ISA extensions, border splitting or output-channel blocking are enabled.

Node 58's hot reduction at `0x80004b00..0x80004b7e` executes 35 instructions per eight products: 16 byte loads, eight `mulw`, eight accumulator additions, two pointer increments and one branch. It contains no stack accesses, dynamic tensor indexing or per-product zero-point additions. This describes the linked ELF, not an expectation based on C++ syntax. Node 4's short K=16 reduction is expanded by GCC; isolated and in-model measurements agree.

## Footprint and memory

| Category | A0 bytes | B1 bytes | Change |
|---|---:|---:|---:|
| Executable code | 23,240 | 24,352 | +1,112 |
| Actual read-only sections | 4,868,072 | 4,916,136 | +48,064 |
| Planned constants/parameters | 4,867,424 | 4,915,488 | +48,064 |
| Activation arena | 1,505,280 | 1,505,280 | 0 |
| Linked BSS | 1,505,424 | 1,505,424 | 0 |

The extra 48,064 bytes hold 12,016 corrected biases. Original biases and weights remain available in compiled constants. There is no scratch allocation. The baseline-input stack watermark is 416 bytes; it is an observation, not a universal stack bound.

| Global instruction category | A0 | B1 |
|---|---:|---:|
| load | 821,653,417 | 811,897,315 |
| store | 19,836,200 | 10,080,098 |
| integer_alu | 2,230,445,752 | 1,294,307,096 |
| multiply | 388,650,056 | 388,650,014 |
| conditional_branch | 505,730,836 | 209,509,750 |
| jump | 13,868,232 | 13,868,232 |
| custom | 0 | 0 |

Most savings are arithmetic/address and loop-control instructions. This first kernel still loads each activation separately for each output channel; activation reuse is a later blocking experiment. Global load-plus-store instructions per useful executed product decrease from 2.207 to 2.156. A multiply opcode is not treated as proof of useful MAC work.

## Evidence and reproduction

- Full capture: `57fa9463fd9065d3ad8ff92493444cc5a2ce19e5e68d9399e35058238f0f859e` under `build/profiling/compiler/`.
- Parent capture: `be93754b9e78bd63475c266fe05bea45f80541d015b081eb264cdb3534c6b5fd`.
- ELF: `627b914ded75e7c3ad6c07e076a9509db4e18968c22ba45822dea6a513c14c8d`.
- Replay: `560f219de0e5d077f671b7d718508437624d6697b567f9322572ec215e96dd5e` under `build/compiler/B1-replay/`: nodes 4/58 on all eight oracle cases, plus two existing reference scalar-dot fixtures. Microbenchmarks remain separate from the custom kernel measurements.
- GCC: `3125df6ef56b415c6bed804cf87c387222d08434054476d70e6e5346069891e4` under `build/compiler/B1-gcc/`: five executable translation units with nine diagnostic stages each, with identical loadable bytes.
- Viewer export: `build/explorer/B1-pointwise.zip`, using the same capture and GCC evidence.
- Rebuild/correctness/repeated profiling: `gmake compiler-b1-checkpoint`.
- Isolated replay: `python tools/profile_compiler.py replay --build-manifest build/compiler/B1/rv64/build.json --host-build-manifest build/compiler/B1/native/build.json --nodes 4,58 --cases all --kinds native,sanitized,rv64 --output-root build/compiler/B1-replay --results-dir results/profiling/B1-pointwise-replay`.
- GCC: `python tools/profile_compiler.py analyze --build-manifest build/compiler/B1/rv64/build.json --output-root build/compiler/B1-gcc --results-dir results/profiling/B1-pointwise-gcc`.

Builds retain `-O2` and `rv64imc/lp64`. The kernel uses selective eight-lane scalar unrolling. Generated code, actual dependencies, prepared constants, commands and ELF identities are frozen in content-addressed build evidence. Default viewer bundles exclude weight payloads.

The known all-131 input still reports the pinned Softmax domain failure at node 62, without exposing a final output. It is not a successful performance case. B0 files remain frozen. A0 was rebuilt for current provenance and its allocated sections and loadable segments match the previous A0 image exactly; only debug/evidence identity changes.

## Next independent work

Pointwise kernels remain approximately 62.2% of B1 retirements. The next pointwise candidate is output-channel blocking with activation reuse. Depthwise is now approximately 26.4%; stem is approximately 10.2% and its previously measured unrolling candidate remains available. These changes require separate checkpoints and full repeat profiles; this checkpoint does not enable them.
