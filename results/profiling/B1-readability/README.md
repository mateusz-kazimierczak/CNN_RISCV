# Compiler and viewer-source readability pass

The existing standalone B1 implementation was committed and pushed to `origin/litert`
as `a638c6a22c2a3db837d6f24f5ac0590d57a2c272` **before** these edits. The readability changes remain uncommitted.

**Performance gate: PASS.** Before and after both retire **1,792,953,997 instructions**.
Every allocated section and ELF load segment is identical, including code, data,
layout and addresses. All 64 unit metrics and invocation overhead are unchanged.
The parent and new event/PC CSV files match byte-for-byte, as do both new repeats.
The full ELF hashes differ because debug/source evidence changes.

| Measurement | Before | After |
|---|---:|---:|
| Full instructions | 1,792,953,997 | 1,792,953,997 |
| Executable code | 50,652 bytes | 50,652 bytes |
| Read-only sections | 4,915,984 bytes | 4,915,984 bytes |
| Activation arena | 1,505,280 bytes | 1,505,280 bytes |
| BSS | 1,505,424 bytes | 1,505,424 bytes |
| Observed canonical stack watermark | 536 bytes | 536 bytes |

## What changed

- Generated B1 wrappers describe each logical node and tensor's ID, shape, dtype
  and layout. Template values and runtime operands are labelled and placed on
  separate lines. Labels are comments, not new runtime objects or instructions.
- The generated preamble explains activation byte offsets, original tensor
  constants and prepared parameter offsets in INT32 elements. It distinguishes
  logical operands from prepared replacements, including corrected biases.
- Project stem, FC, ADD, pooling and boundary kernels use descriptive dimensions,
  coordinates, accumulators and pointers. Comments explain input/output offsets,
  padding, channel reuse, bias placement and rounding without changing loop order.
- Depthwise names its interior rectangle and clipped border ranges explicitly;
  pointwise distinguishes a scalar input value from a group pointer and describes
  independent blocked accumulators. Function names, attributes and layouts stay fixed.
- Softmax names fixed-point intermediates and separates its final expression into
  readable stages. Comments document Q5.26, Q0.31, Q2.29 and Q12.19 formats, polynomial
  coefficients, reciprocal iterations and the existing exponent failure. A compile/link
  check confirmed that the named stages retain identical loadable bytes.
- Python runtime selection separates supported-geometry checks from evidence-contract
  construction. The emitter uses a common labelled-call formatter. Canonical kernel,
  memory and prepared plans and constant payloads remain identical.

The public kernel interfaces, optimization flags, unrolling choices, arithmetic
backend, quantization order, guards and invocation boundaries are unchanged. A0's
C++ source remains byte-identical; its production ELF and all 40 frozen B0 files
are unchanged.

## Validation

Native, capture, sanitized and RV64 correctness gates pass. Each capture/sanitized
build compares 510 complete intermediate arrays across eight oracle inputs; the
known all-131 Softmax diagnostic remains unchanged. Ordinary Spike and both full
captures compare all 1,000 public bytes for canonical seed 1. No failure is counted
as a successful full-inference performance result.

In addition to the current standalone image, nine previous B1 configurations were
regenerated and rebuilt: pointwise OC1, stem unrolling, OC2, OC4, 3x3-only depthwise,
5x5-only depthwise, both depthwise families, project numerics and project kernels.
Every rebuilt image has identical allocated sections and load segments to its
respective predecessor. Kernel/memory/prepared plans and constant files also match.
`verification.json` records each compared ELF identity and flag set.

**193 compiler tests pass** (281.974 seconds), alongside five collector fixtures,
four frozen-source/export tests and six B1 browser scenarios. The viewer test reads
the actual labelled generated calls and the edited Softmax source, and confirms
its displayed full-inference count. Source screenshots were visually inspected.
No viewer product code was changed.

GCC analysis recompiles all five executable translation units with nine diagnostic
stages and requires identical loadable bytes. The new bundle uses the new ELF's
DWARF and frozen source snapshots, rather than attaching old line locations to new
source. Register locations, loop roles, compiler analysis and coverage limits
remain exposed. Source-line instruction counts are attribution, not line executions;
comments and labels are compiler-known documentation, not inferred measurements.

## Evidence and reproduction

- Parent capture: `9a880237526864575d888bc39fc88a1d96c3c827c26c49cb303bdaf573a893fc`.
- New capture: `e098cc5d9eea5f3512f584e642d30032c9d83b31998d8a4cc33f82a6a0bbf59e`.
- Previous full ELF: `5445775f5503b3a6426456074d69ab41fb225f268f28724431cca6d1b1a42bf8`.
- New full ELF: `fc7d6ba8e903609a6a71c012048abb881d6a90582a37f609eb92373e70d7ec37`.
- GCC analysis: `0f266768d3abfabbbcf9a104b7618e2639443126e03a58c0d52c7cc475f8be06`.
- Portable viewer: `build/explorer/B1-readable.zip`.
- Detailed build logs and screenshots: `build/compiler/B1-readable/`.
- Variant image checks: `build/compiler/B1-readable/variant-verification.json`.

```sh
gmake compiler-b1-readable-checkpoint
uv run --python 3.12 python tools/profile_compiler.py analyze \
  --build-manifest build/compiler/B1-readable/rv64/build.json \
  --output-root build/compiler/B1-readable-gcc --results-dir results/profiling/B1-readable-gcc
uv run --python 3.12 --with pyelftools==0.32 python tools/profile_compiler.py export \
  --capture build/profiling/compiler/e098cc5d9eea5f3512f584e642d30032c9d83b31998d8a4cc33f82a6a0bbf59e \
  --compiler-analysis build/compiler/B1-readable-gcc/latest.json \
  --output build/explorer/B1-readable.zip
```

Override `B1_READABILITY_PARENT_CAPTURE` when restoring the prior standalone capture
elsewhere. Rebuilt artifact identities may change; use the newly emitted capture ID
for export. Binary/source snapshots and raw captures remain in ignored build storage.
Hardware cycle measurements are separate; no new timing result is claimed here.
