# B1 specialized depthwise kernels — Stage 6

**Accepted: 3×3 and 5×5 specialization together.** Full inference falls from 2,215,157,070 to **1,874,851,486 retired instructions** (15.36% fewer). All 16 depthwise units improve; all other 48 units and the 84-instruction invocation overhead are unchanged. Stem unrolling and pointwise OC4 remain selected.

| Selection | Full retired instructions | Fewer vs OC4 | Executable bytes | Additional bytes |
|---|---:|---:|---:|---:|
| Parent OC4 | 2,215,157,070 | 0.00% | 38,336 | 0 |
| B1-depthwise3 | 2,020,756,876 | 8.78% | 43,252 | 4,916 |
| B1-depthwise5 | 2,069,251,680 | 6.59% | 46,160 | 7,824 |
| B1-depthwise | 1,874,851,486 | 15.36% | 51,072 | 12,736 |

The independently measured 3×3 and 5×5 savings add exactly to 340,305,584 instructions. Each selected unit has exactly the same count in its family-only and combined capture; unrelated units retain their parent counts. No results are inferred by subtracting unmeasured hypothetical builds.

| Node | Filter | Parent | Specialized | Fewer instructions |
|---:|---|---:|---:|---:|
| 2 | 3×3 | 104,625,788 | 48,011,361 | 54.11% |
| 5 | 3×3 | 64,107,723 | 32,089,412 | 49.94% |
| 8 | 3×3 | 125,589,275 | 56,806,696 | 54.77% |
| 12 | 5×5 | 58,712,426 | 24,287,381 | 58.63% |
| 15 | 5×5 | 75,625,351 | 42,275,283 | 44.10% |
| 19 | 3×3 | 9,220,695 | 5,047,607 | 45.26% |
| 22 | 3×3 | 25,859,214 | 12,562,576 | 51.42% |
| 26 | 3×3 | 25,859,227 | 12,562,589 | 51.42% |
| 30 | 5×5 | 36,358,362 | 22,893,367 | 37.03% |
| 33 | 5×5 | 51,299,274 | 32,091,093 | 37.44% |
| 37 | 5×5 | 51,298,506 | 32,090,325 | 37.44% |
| 41 | 5×5 | 16,605,687 | 8,762,979 | 47.23% |
| 44 | 5×5 | 20,370,971 | 14,235,567 | 30.12% |
| 48 | 5×5 | 20,371,113 | 14,235,709 | 30.12% |
| 52 | 5×5 | 20,371,096 | 14,235,692 | 30.12% |
| 56 | 3×3 | 13,915,078 | 7,696,565 | 44.69% |

Compared with B0 (4,867,278,370), the accepted build retires 61.48% fewer instructions. Compared with the corrected static-metadata A0 (3,980,184,493), it retires 52.90% fewer. These are instruction-count comparisons, with no claim about cycle speedup.

## Implementation and numerical contract

`kernels/rv64imc/depthwise.h` uses fixed square filters, constant NHWC/1HWO strides, separate interior spans, and border clipping once per pixel. Interior tap reductions are unrolled; borders visit only valid rows and columns. Invalid input pointers are never formed. The supported subset has depth multiplier one, dilation one and strides one/two; unsupported geometry retains the reference kernel. Selection uses geometry, with independent `--depthwise-kernels 3` and `--depthwise-kernels 5` switches. Saved plans restore and validate these choices.

Accumulation preserves row-major tap order, input offset only on valid taps, bias after reduction, and pinned reference double-rounding requantization and activation clamps. Existing offline prefix bounds still apply. Full-filter corrected biases are not used at borders. Constants, original weight layout, physical tensor/parameter placements, lifetimes and arena/scratch requirements are unchanged. The memory-plan identity changes because implementation contracts change. No new ISA instruction or global GCC flag is enabled.

## Assembly and dynamic instruction mix

The measured node-8 interior at `0x80007ca0` contains nine scalar product sites with fixed tap offsets (weight offsets 0, 144, …, 1152) and no tap-loop or padding branches. Its border reduction advances input and weight pointers by 144 bytes per tap and uses clipped loop bounds. The node-15 interior similarly expands 25 tap sites. These observations come from the linked RV64 ELF and verified GCC assembly; address values apply only to the accepted ELF. Channel, spatial, bias/quantization and border control remain.

| Full-inference instruction category | Parent | Specialized | Change |
|---|---:|---:|---:|
| conditional_branch | 157,578,470 | 73,861,763 | -83,716,707 |
| custom | 0 | 0 | +0 |
| divide_remainder | 0 | 0 | +0 |
| integer_alu | 1,108,794,780 | 842,546,375 | -266,248,405 |
| jump | 13,868,232 | 13,504,290 | -363,942 |
| load | 536,955,238 | 544,978,875 | +8,023,637 |
| multiply | 388,650,126 | 389,255,640 | +605,514 |
| other | 0 | 0 | +0 |
| store | 9,310,224 | 10,704,543 | +1,394,319 |

Integer ALU and branch reductions dominate. They are instruction categories, not an exact semantic decomposition into indexing versus arithmetic. Memory instructions increase from **546,265,462 to 555,683,418 (+9,417,956)**; compiler-generated spills and helper call frames remain visible. Node 8 increases from 12,000,411 to 13,294,378 memory instructions; node 15 increases from 10,124,186 to 10,591,509. These costs are included in the accepted total.

Useful executed products remain **381,239,488** and logical graph MACs remain **385,187,552**. The report derives these from the declared algorithm, not multiply-opcode counts. The small increase in multiply instructions is not additional useful model work. Exact memory-instruction/product and MAC/instruction ratios, instruction mix and evidence scopes are in each profile summary.

## Memory and correctness

Executable sections grow from 38,336 to 51,072 bytes (+12,736). Read-only sections remain 4,916,136 bytes; planned constants/parameters remain 4,915,488 bytes; the activation arena remains 1,505,280 bytes and BSS remains 1,505,424 bytes. There is no arena scratch. The observed canonical-input stack watermark rises from 416 to 536 bytes; this includes the collector-independent stack-paint safety gap and is not a proof of minimum SP or a universal bound.

All three variants pass native release, capture, sanitized and RV64 correctness. Each capture/sanitized build compares 510 complete intermediate arrays across eight inputs (seven successful full outputs plus 62 prefix arrays for the known failing Softmax input). Ordinary Spike and both repeated production profiles compare all 1,000 public bytes on canonical seed 1. Every execution unit and PC reconciles. B0’s 40 frozen files and the A0 production ELF remain unchanged.

Nodes 8 and 15 additionally pass complete isolated replay on all eight cases in native, sanitized and RV64 executables: 18 fixtures per build, including two existing reference scalar-dot microbenchmarks. Replay uses frozen lowered code and verified oracle snapshots, with restoration, guards and comparisons outside the measured region. Its instruction counts and ELF identity remain separate from production. The microbenchmarks do not measure the depthwise kernel.

Direct ASan/UBSan numerical tests compare **320 kernel cases / 20,482,432 output bytes** against pinned TFLM, including asymmetric SAME and VALID padding, both filter sizes, stride one/two and mixed-axis strides, odd channel counts, multiple batches, null/present bias, positive/negative shifts, extreme input values and activation clamps. Tiny inputs exercise no-interior paths; guards and immutable operands are checked.

Compiler tests: **184 passed** (261.526 seconds); depthwise selection/numerics tests: 6; collector fixtures: 5; compiler export: 4; B1 browser scenarios: 4. GCC analysis rebuilds all five executable translation units with nine diagnostic stages and requires identical loadable bytes. Viewer acceptance checks both implementations, border choices, frozen header/source navigation and measured counts.

The all-131 full-model input still fails the existing Softmax-domain diagnostic at node 62. Passing earlier isolated depthwise nodes on that input does not turn it into a successful full-model performance result. Hardware timing, caches and custom ISA are outside this checkpoint.

## Evidence identities

Parent capture: `482d18bbff4c7df63fe41c90ca8d30d81b53807816528eeb13da6eb30038e41f`.
- **B1-depthwise3**: capture `b1b1b2ef7e6641ebb2c86e1889623d162a3cbe33143412e6d63648a63b76d605`; ELF `9dabb5b25d62469d88efbd4cb6080fed4707ab4039e8c0521f499b24d46bcbd3`.
- **B1-depthwise5**: capture `a29dde566c5208af1edfb6a75ae53c8f21099273327deadd438f78b6c263ce27`; ELF `c75b7f4435f32c703a51ced881519546d049c902f61a984cffeb731c5e9afa03`.
- **B1-depthwise**: capture `228637b6b0a191eb384c8e6ebb62dc56fb887780a6177e2e1dbd3efde5ba9760`; ELF `30987a4a2a400e386a5819b9498c82b448d4da46c84e93b20131b1e4216a4068`.
- Replay: `41baf1a513cb3e11287f1e4414bd96e1ce2659f53814303f0b4e31d344e40e6a`; fixture pack `aa63b2ad539441c94f75211f84746663959e1c1c55d9b875d479f433aeb72eee`.
- GCC analysis: `b30c066204bf701a36c0e51234133b9512da237ac47d13a8f774d64a245c67e1`.
- Portable viewer: `build/explorer/B1-depthwise.zip`.
- Immutable full profiles: `build/profiling/compiler/<capture-id>/`; source/ELF snapshots: `build/compiler/<variant>/rv64/evidence/`. These ignored artifacts must be retained or restored for offline inspection.

## Reproduction

```sh
gmake compiler-b1-depthwise-checkpoint
gmake compiler-b1-depthwise3-checkpoint
gmake compiler-b1-depthwise5-checkpoint
uv run --python 3.12 python tools/profile_compiler.py replay \
  --build-manifest build/compiler/B1-depthwise/rv64/build.json \
  --host-build-manifest build/compiler/B1-depthwise/native/build.json \
  --nodes 8,15 --cases all --kinds native,sanitized,rv64 \
  --output-root build/compiler/B1-depthwise-replay \
  --results-dir results/profiling/B1-depthwise-replay
uv run --python 3.12 python tools/profile_compiler.py analyze \
  --build-manifest build/compiler/B1-depthwise/rv64/build.json \
  --output-root build/compiler/B1-depthwise-gcc --results-dir results/profiling/B1-depthwise-gcc
uv run --python 3.12 --with pyelftools==0.32 python tools/profile_compiler.py export \
  --capture build/profiling/compiler/228637b6b0a191eb384c8e6ebb62dc56fb887780a6177e2e1dbd3efde5ba9760 \
  --compiler-analysis build/compiler/B1-depthwise-gcc/latest.json \
  --output build/explorer/B1-depthwise.zip
```

`B1_DW_PARENT_CAPTURE` overrides the restored OC4 parent path. Rerun export using the new content ID produced by a rebuild. Full profiling remains outside routine unit tests.

**Gates: PASS.** Stop after Stage 6. Further software tuning or Xqmac integration requires a new request and separately attributed measurements. Changes remain uncommitted.
