# B1 stem unrolling checkpoint

The opt-in stem code-generation choice saves **150,565,980 retired instructions (5.52%)** over the pointwise-only B1 checkpoint. Exactly one execution unit changes: the stem. The other 63 units retain identical instruction counts, including all 32 custom pointwise kernels.

| Scope | Pointwise-only B1 | B1 with stem unrolling | Reduction |
|---|---:|---:|---:|
| Full invocation | 2,728,312,505 | 2,577,746,525 | 5.52% |
| Stem | 277,049,718 | 126,483,738 | 54.35% |
| Other 63 execution units | 2,451,262,703 | 2,451,262,703 | 0% |

B0 retires 4,867,278,370 instructions; this build is **47.04% lower**. A0 static-metadata retires 3,980,184,493; this build is 35.24% lower. Ratios describe instruction counts, not hardware timing.

## Change

`--config B1 --stem-unroll` adds the kernel-plan choice `gcc_rv64_function_unroll_loops` to the RGB 3x3, stride-two, dilation-one reference convolution. Selection uses geometry, not node number. The generated wrapper receives `B1_STEM_UNROLL`, which expands to `__attribute__((optimize("unroll-loops")))` only under RV64 GCC. Other builds compile the same numerical body without that target attribute. Global compilation stays at `-O2`, with the pinned GCC 15.2 toolchain and RV64IMC/lp64.

This retains the pinned reference implementation, border behavior and double-rounding quantization. It does not introduce a new arithmetic kernel or ISA instruction. A0 rejects the option; B1 without the option retains its previous selection. Saved enabled plans round-trip without repeating the CLI option. Conflicting, unknown, duplicated or misplaced selections are rejected before emission.

Generated-source comparison proves that only the stem wrapper declaration changes, plus its guarded macro. Constants, prepared parameters and the complete memory plan are byte-identical to the parent artifacts. The function-local option lets GCC expand short loops and avoid the previously expensive address/stack handling. Exact retirement captures establish the effect; exposing constants alone had not guaranteed better code.

## Stem instruction mix

| Category | Before | After | Change |
|---|---:|---:|---:|
| load | 44,700,045 | 23,567,133 | -21,132,912 |
| store | 1,204,238 | 401,871 | -802,367 |
| integer_alu | 195,966,346 | 84,506,605 | -111,459,741 |
| multiply | 11,175,008 | 11,175,120 | +112 |
| conditional_branch | 23,201,264 | 6,030,192 | -17,171,072 |
| jump | 802,817 | 802,817 | +0 |
| custom | 0 | 0 | +0 |

The stem still executes 10,773,600 useful products (logical graph estimate: 10,838,016). The multiply-opcode count increases by 112 despite lower total instructions; opcode counts are not used as proof of useful MAC work.

## Footprint

| Storage | Parent bytes | New bytes | Change |
|---|---:|---:|---:|
| Executable code | 24,352 | 24,600 | +248 |
| Actual read-only sections | 4,916,136 | 4,916,136 | 0 |
| Planned constants/parameters | 4,915,488 | 4,915,488 | 0 |
| Activation arena | 1,505,280 | 1,505,280 | 0 |
| Linked BSS | 1,505,424 | 1,505,424 | 0 |

The stem wrapper grows from 396 to 646 bytes; other layout/alignment changes make the total code increase 248 bytes. No scratch or constant storage is added. The canonical-input observed stack watermark remains 416 bytes, not a universal stack bound.

## Evidence

- Full capture: `62c8e308b8ffd071a3db39d21f6bfaea54cdfaa328e3577896d1e547fdd19964` under `build/profiling/compiler/`; two byte-identical event/PC captures reconcile all 64 units and 84 invocation-overhead instructions.
- Parent capture: `57fa9463fd9065d3ad8ff92493444cc5a2ce19e5e68d9399e35058238f0f859e`.
- ELF: `03d836651e16c59160f26287a1f1ac1be991ecfc8ff11bfd53fe7afcafe77e71`.
- Replay: `91e6581c75dd18aa06d8bc8eef38f2a595ebe854dc3b0f33f455ba9457778bd2` under `build/compiler/B1-stem-replay/`: all eight stem inputs with complete 401,408-byte outputs, plus the two existing reference scalar-dot microbenchmarks. These microbenchmarks remain distinct from stem measurements.
- Replay fixture-pack SHA-256: `fd7875312447ff0e54a3ad810dfc8b2a0b0bd5d089a39edebb0f8700e90093ea`.
- GCC analysis: `0d00fd587086f8d9a4fced1a4e7809cecb9e9a51ebe394bfbf8aea9f7f28393a` under `build/compiler/B1-stem-gcc/`: five executable translation units, nine diagnostic stages each; loaded bytes match the measured ELF.
- Viewer bundle: `build/explorer/B1-stem-unroll.zip`; the browser test checks the saved code-generation choice, generated source and full measured count. Default bundles omit weights.
- Native and sanitized diagnostic builds each compare all 510 available node arrays across eight oracle cases. Native release compares all seven successful full outputs. Ordinary Spike and repeated full captures compare all 1,000 public output bytes for canonical seed 1.
- Isolated RV64 stem replay compares all eight complete outputs, including the zero-point input whose stem is valid. Full-model zero-point input still returns the known Softmax domain error at node 62 without exposing a final output; no successful full-inference performance result is claimed for it.
- A0 ELF remains `38f37d21f5a6ad833e7b86f53a2cf7f811fa138603e2d7b40312630cb5583fce`; all 40 frozen B0 files remain unchanged.

## Reproduction

```sh
gmake compiler-b1-stem-checkpoint

python tools/profile_compiler.py replay --build-manifest build/compiler/B1-stem/rv64/build.json --host-build-manifest build/compiler/B1-stem/native/build.json --nodes 1 --cases all --kinds native,sanitized,rv64 --output-root build/compiler/B1-stem-replay --results-dir results/profiling/B1-stem-unroll-replay

python tools/profile_compiler.py analyze --build-manifest build/compiler/B1-stem/rv64/build.json --output-root build/compiler/B1-stem-gcc --results-dir results/profiling/B1-stem-unroll-gcc
```

The checkpoint target writes a separate `build/compiler/B1-stem/` directory and reports to `results/profiling/B1-stem-unroll/`. Override `B1_STEM_PARENT_CAPTURE` when restoring captures elsewhere. Build snapshots preserve generated source, compiler identity, actual dependency bytes and hashes, commands, flags, execution/memory plans and linked ELF identity.

Only this stem choice is enabled in this checkpoint. Output-channel blocking and depthwise changes remain separate future experiments.
