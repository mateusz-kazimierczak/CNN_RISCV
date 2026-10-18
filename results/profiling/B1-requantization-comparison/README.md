# B1 software requantization specialization

**Selected checkpoint: PASS.** The combined binary retires **1,650,025,771
instructions**, saving **142,928,226 (7.972%)** against the previous readable B1.
All 49 affected units improve and the other 15 retain their counts. Every PC
reconciles: the 64 unit totals plus 84 invocation instructions equal full inference.
This is a software-only RV64IMC change with unchanged `-O2`/ISA flags and no
custom instructions. Spike counts do not establish hardware timing.

## Comparison

| Configuration | Full retirements | Fewer vs previous B1 | Memory instructions | Executable bytes |
|---|---:|---:|---:|---:|
| Previous readable B1 | 1,792,953,997 | 0.000% | 556,873,761 | 50,652 |
| Generic policy control | 1,792,953,997 | 0.000% | 556,873,761 | 50,660 |
| Out-of-line specialization | 1,694,945,564 | 5.466% | 556,873,761 | 50,712 |
| Broad inline specialization | 1,671,976,400 | 6.747% | 588,873,924 | 58,132 |
| Selected inline specialization | 1,650,025,771 | 7.972% | 559,509,746 | 54,520 |

Every row has two byte-identical event/PC captures, 64 expected execution units
and all 1,000 public output bytes compared. Counts use the canonical seed-1
input and the ordinary optimized correctness ELF. Input preparation, stack
painting, output verification and printing remain outside inference.

The generic policy control has identical per-unit counts, instruction mix and
memory traffic to the old B1. Its code grows eight bytes after introducing policy
types; executable layout is not claimed byte-identical. Thus the reported
instruction savings come from specialization rather than the policy adapter.

Broad inlining makes 13 units worse than the old B1 and 24 worse than the
out-of-line specialization. It also adds 32,000,163 memory instructions. It is
retained as an explicitly named experiment, not the selected checkpoint.
The selected configuration uses the out-of-line helper by default and explicitly
inlines the 25 logical units that improved in the full-policy experiments:

`1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 18, 19, 20, 21, 22, 25, 26, 29, 41, 44, 48, 52`.

The node list belongs to the Make checkpoint configuration, not the selector.
Kernel plans preserve and validate every override. The combined ELF is measured
independently; its counts are not synthesized by adding earlier measurements.
GCC generates a further 370,341-instruction reduction in node 41 in the combined
build, so summing the minima of the experiments would not give its actual total.

| Representative logical node | Before | Selected | Fewer instructions |
|---|---:|---:|---:|
| 1 | 90,810,140 | 78,960,244 | 13.05% |
| 4 | 118,477,195 | 97,978,634 | 17.30% |
| 8 | 54,548,776 | 38,351,741 | 29.69% |
| 15 | 41,334,483 | 35,403,916 | 14.35% |
| 58 | 69,949,393 | 69,066,916 | 1.26% |
| 61 | 6,931,437 | 6,931,437 | 0.00% |

## Arithmetic and compiler changes

The compiler verifies multiplier arrays in `[0, INT32_MAX]` and shift arrays in
`[-31, 0]` before selecting either specialized policy. Positive-shift or unrelated
operators retain their original arithmetic; explicit overrides targeting an
unsupported/unproven unit are errors. Unknown policies, forged metadata, duplicate
CLI node IDs and conflicting saved-plan options are rejected.

A nonnegative multiplier rules out the one saturating high-multiply case. There
is no positive left shift. For negative product `p`, the pinned result
`trunc((p - 2^30 + 1)/2^31)` equals `floor((p + 2^30)/2^31)`. The helper therefore
uses a 64-bit product, a constant nudge and arithmetic right shift for both signs,
then retains the separate rounded power-of-two division. Negative halfway cases
and double rounding are preserved exactly. The out-of-line helper is 52 code
bytes and has no conditional branch; the original generic helper remains for
other operators and comparisons. GCC decides which inline-policy calls to inline;
some remain out of line, as recorded by assembly and exclusive function counts.

Reusable kernels accept a compile-time scaling policy. Their reduction order,
operand layouts, corrected biases, prepared constants and memory contracts do not
change. The execution plan exposes scaling separately from reduction, leaving a
clear integration point for later X2 instructions without attributing B1 gains to
an ISA extension.

## Costs and memory

The selected build adds **2,635,985 memory instructions (+0.473%)**, **3,868 code
bytes (+7.64%)** and raises the observed canonical-input stack watermark from
**536 to 584 bytes**. The out-of-line alternative keeps the old memory traffic
and stack watermark and saves 5.466%, so it remains available as the smaller-code
alternative. Hardware measurements may favor a different policy.

The entire net increase in memory instruction count matches the increase in
decoded SP-relative accesses: loads 16,764,213 -> 19,057,290; stores 3,842,667 ->
4,185,575. This is direct `x2` operand attribution, not a complete semantic
classification of spills. [Counts and scope](stack-accesses.json).

All builds retain 381,239,488 useful executed products and 385,187,552 graph MACs;
multiply opcode counts are not substituted for either metric. Selected useful
products/instruction improve from 0.212632 to 0.231051; memory instructions/product
increase from 1.460693 to 1.467607. Arena size stays 1,505,280 bytes, planned
constants/parameters 4,915,488 bytes, allocated read-only storage 4,915,984 bytes
and BSS 1,505,424 bytes. No extra arena scratch or weight repacking is introduced.

## Correctness and visibility

- Both arithmetic helpers match independently compiled pinned upstream routines
  under ASan/UBSan on 6.4 million random scale cases each, all 32 supported shifts,
  signed endpoints, multiplier extremes and directed rounding transitions.
- The selected native, capture and sanitizer executables pass all eight oracle
  cases. Each capture/sanitizer build compares 510 complete intermediate arrays.
  The known all-131 Softmax failure retains status 2 and the 62-node prefix; it is
  never presented as a successful inference/performance result.
- Ordinary RV64 verification compares all 1,000 public bytes. The selected capture
  repeats event and PC files byte-for-byte, with exact per-PC conservation.
- Replay restores nodes 1, 4, 8, 15, 58, 61 and 62 on all eight cases, plus two
  checked scalar-dot fixtures: **58 fixtures per native/sanitized/RV64 executable**.
  Complete outputs, guards, diagnostic failure and repeated RV64 captures pass.
  Isolated counts remain separate from production.
- The 198-test compiler suite passes; the final six-test policy-selection suite
  additionally validates per-node overrides and saved-plan/CLI conflicts. Five
  collector fixtures pass. Logs and identities are bound in
  [verification.json](verification.json).
- GCC diagnostics cover five executable translation units and loadable bytes
  match the measured ELF. The exported v2 viewer bundle has seven passing real
  B1 browser scenarios, including policy metadata, generated source, numerical
  comments and the measured total. Default export excludes weight payloads.
- The frozen B0 archive verifies unchanged. Refreshed A0 native/capture/sanitized
  and ordinary RV64 correctness gates pass; its production ELF remains
  `38f37d21f5a6ad833e7b86f53a2cf7f811fa138603e2d7b40312630cb5583fce`.

## Artifact identities and reproduction

The existing readability work was committed and pushed as `68806aa` before this
optimization. The optimization and these new results are not committed yet.

- **B1-readable**: `e098cc5d9eea5f3512f584e642d30032c9d83b31998d8a4cc33f82a6a0bbf59e`; ELF `fc7d6ba8e903609a6a71c012048abb881d6a90582a37f609eb92373e70d7ec37`.
- **B1-requantization-control**: `098070385d7588b4d69a524b7cdacfe24ccf29bd8075f82b28937cf685e6cc39`; ELF `79966fb2631c8c98533e62a856855b64313c2627080d4577bd666358590d89af`.
- **B1-requantization**: `416445553a26b5639e9014ba73047dc354a2609d208e09e7b3b6c77e2c230b5f`; ELF `8c6c2f42c59a9827fd35a2b4c3b427dc9a1750090a390f99c0c47357cc59f19a`.
- **B1-requantization-inline**: `5987138446d35db94636b56354544f6bd6c780f68d60b329360773e2905730ec`; ELF `0cced4586d318d03a6615211ca992834b6e707e842a19ebf2d1807cbe14eb694`.
- **B1-requantization-selected**: `36c3ac40b6ebb1bb8985b0c6990e88b48def27f0ce5af60faa0a6099aca2d291`; ELF `2bd4ec9083ea15912fb2accafd926876d237088aacb231250990f3803c41ac1a`.

Selected GCC artifact: `b960d0c6680fdb137b186409a8861b67ca45b1e1c0a30c226ece99d15866fe48`. Replay artifact:
`33fe3f3d786969027f254711f937d1ba39ec667f538b72ff41993e7d9b5b993b`; fixture pack `ddd3121cb9516d7dd9ebc7520958d51cf9c2d2b23f42e2e131e9b0a60a9455fa`.
Viewer: `build/explorer/B1-requantization-selected.zip`.
Full captures, binaries, source snapshots, GCC dumps and replay evidence remain
in ignored `build/` storage; retain those directories for offline investigation.
Compact summaries in adjacent results directories identify each build/capture.

```sh
gmake compiler-b1-requantization-checkpoint
gmake compiler-b1-requantization-inline-checkpoint
gmake compiler-b1-requantization-selected-checkpoint
uv run --python 3.12 python tools/profile_compiler.py replay \
  --build-manifest build/compiler/B1-requantization-selected/rv64/build.json \
  --host-build-manifest build/compiler/B1-requantization-selected/native/build.json \
  --nodes 1,4,8,15,58,61,62 --cases all --kinds native,sanitized,rv64 \
  --output-root build/compiler/B1-requantization-selected-replay \
  --results-dir results/profiling/B1-requantization-selected-replay
uv run --python 3.12 python tools/profile_compiler.py analyze \
  --build-manifest build/compiler/B1-requantization-selected/rv64/build.json \
  --output-root build/compiler/B1-requantization-selected-gcc \
  --results-dir results/profiling/B1-requantization-selected-gcc
uv run --python 3.12 --with pyelftools==0.32 python tools/profile_compiler.py export \
  --capture build/profiling/compiler/36c3ac40b6ebb1bb8985b0c6990e88b48def27f0ce5af60faa0a6099aca2d291 \
  --compiler-analysis build/compiler/B1-requantization-selected-gcc/latest.json \
  --output build/explorer/B1-requantization-selected.zip
```

Regeneration produces fresh evidence identities; use the capture ID emitted by
that run. `B1_REQUANTIZATION_PARENT_CAPTURE` and
`B1_REQUANTIZATION_INLINE_NODES` make parent evidence and selected choices explicit.
