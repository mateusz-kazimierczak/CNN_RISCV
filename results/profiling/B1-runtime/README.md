# Project-owned B1 runtime

**All three checkpoints pass.** The standalone target retires **1,792,953,997 instructions**, 4.37% fewer than the accepted depthwise checkpoint. It compiles and links without a TFLM checkout, headers, `common.cc`, ruy or gemmlowp. The fresh snapshot rebuild has identical loadable bytes.

| Checkpoint | Full instructions | Saved vs previous | Executable bytes |
|---|---:|---:|---:|
| Depthwise parent | 1,874,851,486 | — | 51,072 |
| B1-numerics | 1,843,170,046 | 31,681,440 (1.690%) | 51,188 |
| B1-project-kernels | 1,793,359,106 | 49,810,940 (2.702%) | 52,052 |
| B1-standalone | 1,792,953,997 | 405,109 (0.023%) | 50,652 |

Overall savings are 81,897,489 instructions and 420 code bytes. Compared with B0 (4,867,278,370), the target retires 63.16% fewer instructions. Compared with corrected static-metadata A0 (3,980,184,493), it retires 54.95% fewer. These ratios do not measure hardware timing.

## 1. Numerical compatibility layer

`kernels/project/quantization.{h,cc}` owns signed high multiplication, sign-sensitive power-of-two rounding and scalar double-rounding scaling. `quantization_select.h` chooses the numerical backend for the custom convolution kernels. The default reference selection remains available; `--runtime project-numerics` explicitly selects the new helper. No checkpoint label changes code.

The port preserves the pinned formulas and valid INT32 input contracts. Offline range proofs are retained; no signed wrapping is substituted for invalid arithmetic. The changed helper emits a different RV64 instruction sequence under the same `-O2` flags and reduces retirements by 31,681,440. Only the 48 custom pointwise/depthwise units change counts in this checkpoint; every other unit is unchanged. Useful model products are not reduced or inferred from multiply opcodes.

Independent ASan/UBSan tests compare 200,000 random scaling/exponential/reciprocal cases, 6,400,000 rounding cases, high-multiply saturation edges and fixed-point exponential transitions against upstream routines. Project tests never generate their expected values using project kernels.

## 2. Remaining operator kernels

`--runtime project-kernels` retains those numerical choices and adds the project RGB 3x3 stride-two stem, FC, equal-shape ADD, global average pooling, boundary conversion and Reshape handling. Depthwise and pointwise remain their existing custom implementations. Unsupported project geometry is rejected explicitly.

| Inclusive unit | Before operator replacement | After | Fewer instructions |
|---|---:|---:|---:|
| 1 | 126,483,738 | 90,810,140 | 28.20% |
| 10 | 8,125,736 | 4,211,880 | 48.17% |
| 17 | 3,397,747 | 1,829,620 | 46.15% |
| 24 | 1,692,848 | 877,362 | 48.17% |
| 28 | 1,691,249 | 922,802 | 45.44% |
| 35 | 2,370,677 | 1,272,950 | 46.30% |
| 39 | 2,372,125 | 1,274,398 | 46.28% |
| 46 | 1,015,835 | 545,308 | 46.32% |
| 50 | 1,015,487 | 544,960 | 46.34% |
| 54 | 1,015,507 | 554,388 | 45.41% |
| 59 | 381,446 | 272,643 | 28.52% |
| 61 | 10,296,433 | 6,931,437 | 32.68% |

The stem preserves row-major valid taps and input offset, with fixed RGB reductions and the prior measured local GCC unrolling choice. FC uses eight-product scalar groups with input offset and an exact tail; it adds bias after reduction. ADD uses statically prepared equal-shape arithmetic; global average pooling preserves signed division and rounding. Boundary conversions preserve exact UINT8/INT8 interpretation. Reshape keeps its proven alias/copy behavior. Boundary and Reshape instruction counts are unchanged; their replacements complete ownership. No weight repacking, new corrected biases or extra scratch are introduced.

Directed ASan/UBSan tests compare 96 stem/FC cases, 400 pooling cases, all 65,536 INT8 ADD input pairs for a nontrivial prepared configuration, and 768 boundary bytes. Cases include optional bias, extreme activations, asymmetric borders, odd pooling counts and reduction tails. All three runtime selections additionally match complete model tensors on eight reference input cases.

## 3. Softmax and target independence

`--runtime standalone` selects the project scalar Softmax exponential and reciprocal algorithms, plus checked normalization. It reuses the checked Q12 sum instead of recomputing the successful preflight, preserving all output bytes and the existing exponent diagnostic. Softmax falls from 703,878 to 298,769 instructions; all other 63 units retain their project-kernels counts.

The known all-131 input still returns status 2 at node 62 before any output write. Its replay validates unchanged poison bytes and explicitly records `performance_result: false`. Node 63 has no oracle input for that failed inference, so it is replayed separately only on the seven successful cases; no missing input or output is manufactured.

Standalone generation emits no `tflite::` call or framework include. The build driver omits upstream include directories, source files, compatibility defines and header inventories, and rejects any actual TFLM compiler dependency. The linked ELF has no TFLM/gemmlowp symbols. The native integration test builds with the configured upstream path unavailable. A separate clean workspace materializes only the verified RV64 snapshot, has no `.deps/tflite-micro` directory, and recompiles/relinks to identical loadable bytes. The standard toolchain and local `tflm/platform/rv64imc/` startup/linker support remain ordinary platform dependencies.

B0, A0, the upstream oracle and offline parameter verification retain pinned TFLM. A0’s production ELF remains `38f37d21f5a6ad833e7b86f53a2cf7f811fa138603e2d7b40312630cb5583fce`; all 40 frozen B0 files remain unchanged. The standalone claim concerns the generated executable, not removal of the reference checkout from the repository.

## Memory, profiling and visibility

Code sections shrink from 51,072 to 50,652 bytes; read-only sections shrink from 4,916,136 to 4,915,984 bytes. Constant payloads, 4,915,488 bytes of planned constants/parameters, physical placements, lifetimes, 1,505,280-byte arena and 1,505,424-byte BSS are unchanged. The observed canonical-input stack watermark remains 536 bytes and is not a universal stack bound.

Total dynamic memory instructions increase from **555,683,418 to 556,873,761 (+1,190,343)**. The reduction in total instructions is primarily arithmetic/control overhead; the memory increase is retained in the report. Useful executed products remain **381,239,488**, and logical graph MACs remain **385,187,552**. Per-unit ratios and instruction mix retain their scopes and measured/derived/unavailable labels. Hardware cycles and cache effects remain unavailable.

Each checkpoint has two identical full event/PC captures, all 64 units plus 84 overhead instructions reconciled, and all 1,000 public bytes compared. Native release, capture, sanitized and ordinary RV64 builds pass; each capture/sanitized build compares 510 complete arrays (seven full cases and the known failure prefix).

Standalone replay covers nodes 0,1,4,8,10,15,58,59,60,61,62 on all eight inputs in native, sanitized and RV64 executables: 90 fixtures per build, including two existing checked scalar-dot microbenchmarks. These cover residual-input restoration, alias restoration and the Softmax failure. Node 63 has seven successful RV64 cases plus two scalar-dot fixtures. All ordinary replay outputs match; repeated RV64 captures match. Isolated counts and ELF identities remain separate from production.

GCC analysis rebuilds all five executable translation units with nine diagnostic stages and identical loadable bytes. The v2 viewer bundle includes project source snapshots, NOTICE/LICENSE attribution, runtime choices, numerical backend and measured counts. It excludes weights and upstream source payloads. Five B1 browser scenarios pass, including all earlier B1 bundles.

The optimized register analyzer reports 2,974 supported locations, 3,729 unsupported expressions and **zero recognized symbolic relationships**. Compiler-known geometry remains in the saved execution plan; loop roles and GCC/source/assembly relationships remain available. No new hash-bound semantic annotations are invented for unreviewed project helpers.

Validation: **193 compiler tests** in 285.625 seconds (including nine runtime/numerical/dependency tests), five collector fixtures, four export tests and five B1 browser scenarios.

## Artifact identities

Parent depthwise capture: `228637b6b0a191eb384c8e6ebb62dc56fb887780a6177e2e1dbd3efde5ba9760`.
- **B1-numerics**: capture `1abb9c425edb7649cd5cc9d9b64831a6ae4847fc199a9684da0f5c32f037aab3`; ELF `3813b31972aa76f9c923ac4f589a38eef59eb3f812cabf703175dafdae4fcebe`.
- **B1-project-kernels**: capture `4ce04be03cfabc010ecfd5efd57b5763c2e830a0a0c67ba8405ba6c53cdaa3f1`; ELF `b639ee7b36b78c75ac88b1f3f44e04e37c5bf71d7e63aefb8d44f2aac3a03e6f`.
- **B1-standalone**: capture `9a880237526864575d888bc39fc88a1d96c3c827c26c49cb303bdaf573a893fc`; ELF `5445775f5503b3a6426456074d69ab41fb225f268f28724431cca6d1b1a42bf8`.
- GCC analysis: `5d38fe2f566ba67d796cdd0fbffbaa38b2eb6803f5ca912d0c0acc9635acae2c`.
- Main replay: `4d095335d8b279deffaba4320ae6495628fbbe1de13cfa730487e81bc9f1e745`; fixture pack `80ba55f4c4c4d0788831d2cabb331e90c71618fef66d83c83dba0564d5b91912`.
- Output replay: `61b270c43f05feb94641217fb981a6e4b635f3963e4dced10a303c18151fd834`.
- Viewer: `build/explorer/B1-standalone.zip`.
- Dependency-free rebuild: `build/compiler/B1-standalone/no-framework/verification.json`.
- Immutable captures: `build/profiling/compiler/<capture-id>/`; verified source/ELF snapshots: each build’s `rv64/evidence/` directory. These ignored files must be retained/restored for offline inspection.

## Reproduction

```sh
gmake compiler-b1-numerics-checkpoint
gmake compiler-b1-project-kernels-checkpoint
gmake compiler-b1-standalone-checkpoint
uv run --python 3.12 python tools/profile_compiler.py replay \
  --build-manifest build/compiler/B1-standalone/rv64/build.json \
  --host-build-manifest build/compiler/B1-standalone/native/build.json \
  --nodes 0,1,4,8,10,15,58,59,60,61,62 --cases all --kinds native,sanitized,rv64 \
  --output-root build/compiler/B1-standalone-replay --results-dir results/profiling/B1-standalone-replay
uv run --python 3.12 python tools/profile_compiler.py analyze \
  --build-manifest build/compiler/B1-standalone/rv64/build.json \
  --output-root build/compiler/B1-standalone-gcc --results-dir results/profiling/B1-standalone-gcc
uv run --python 3.12 --with pyelftools==0.32 python tools/profile_compiler.py export \
  --capture build/profiling/compiler/9a880237526864575d888bc39fc88a1d96c3c827c26c49cb303bdaf573a893fc \
  --compiler-analysis build/compiler/B1-standalone-gcc/latest.json \
  --output build/explorer/B1-standalone.zip
```

The Make targets accept `B1_NUMERICS_PARENT_CAPTURE`, `B1_PROJECT_KERNELS_PARENT_CAPTURE` and `B1_STANDALONE_PARENT_CAPTURE` when restoring different evidence paths. Regenerated manifests produce fresh content IDs; use the emitted capture ID for export. Full checkpoint verification needs the pinned oracle; a standalone target-only build does not need TFLM.

**All gates PASS.** The standalone B1 runtime is complete for the frozen model. Xqmac and hardware evaluation remain separate future work. Changes remain uncommitted.
