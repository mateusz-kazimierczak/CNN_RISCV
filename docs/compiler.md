# Fixed-model compiler

The compiler is a controlled comparison with the unchanged LiteRT Micro B0.
Stage 0 supplies a frozen reference, native tensor oracle, deterministic inputs,
and tests. Stage 1 imports and validates the fixed TFLite graph, preserves its
constants, and exports typed graph IR. Preparing independent quantization
parameters, planning memory, generating inference, and optimizing kernels belong to later
stages of the [design guidelines](../tools/compiler/CUSTOM_COMPILER_DESIGN_GUIDELINES.md).

The pre-implementation project snapshot is commit `02e58f3`. The public compiler
commands accept the exact model identified by the tracked audit:

| Command | Behavior |
|---|---|
| `import MODEL --output-dir DIRECTORY` | Validate and export JSON IR, node table, DOT graph, and manifest |
| `validate MODEL` | Check the supported graph/quantization/shape contract and frozen model identity |
| `inspect MODEL` | Print the validated per-node table |
| `generate MODEL` | Exit 2; inference generation remains gated on Stage 4 |

```sh
gmake compiler-import
gmake compiler-validate
gmake compiler-inspect
```

## Reproduce

Use the existing macOS/Apple Silicon prerequisites in the project README.
The compiler tools use Python 3.12 through `uv`. The Stage 0 tools use the Python
standard library. The Stage 1 frontend pins `tflite==2.18.0`,
`flatbuffers==25.12.19`, and `numpy==2.4.3` in
`tools/compiler/requirements.txt` and checks their installed versions.
The oracle reuses the pinned TFLM native build and its existing third-party
downloads. It does not install a general compiler framework.

```sh
gmake run-native
gmake run-spike
gmake profile-tests
gmake compiler-freeze-b0
gmake compiler-tests
```

`compiler-tests` builds the oracle, captures/verifies the complete input suite,
and runs both stages' tests. To run those steps individually:

```sh
gmake compiler-oracle-build
gmake compiler-oracle
uv run --python 3.12 --with-requirements tools/compiler/requirements.txt \
  python -m unittest discover -s tests/compiler -p 'test_*.py' -v
```

`gmake compiler-frontend-tests` runs the fast Stage 1 checks independently of
native compilation and Spike. For direct CLI use, supply the same pinned environment:

```sh
uv run --python 3.12 --with-requirements tools/compiler/requirements.txt \
  python -m compiler import models/efficientnet-lite0-int8.tflite \
  --output-dir build/compiler/import
```

To repeat the expensive B0 retirement capture without replacing the original B0
captures or results, use a separate verification label. This runs the actual B0
binary; the label does not select a new backend:

```sh
gmake profile-spike PROFILE_CONFIGURATION=B0-stage0
gmake profile-report PROFILE_CONFIGURATION=B0-stage0
```

The verification captures live in `build/profiling/B0-stage0/`. The profiler
writes reports to `results/profiling/B0-stage0/`; the initial Stage 0 verification
reports have been moved to ignored `build/compiler/profiling/B0-stage0-report/`.
The original `results/profiling/B0/` remains unchanged.

## Frozen B0

[baseline.json](../tools/compiler/baseline.json) records the model hash, pinned
revisions/toolchain, input/output contract, counts, reproduction commands, and
SHA-256 hashes of 40 original artifacts. These include native/RV64/debug
executables, both raw captures, the original capture manifest and reports, the
model/audit, and reference source files. The original build Makefile remains
available at the recorded snapshot commit; resolved build flags are in the
archived profiler manifest.

`tools/freeze_compiler_baseline.py` verifies those artifacts, the ELF ISA and
loadable-byte equality, all node/event totals, and repeat agreement before
copying them to `build/compiler/baseline/B0/`. Repeating the command verifies the
archive and refuses to overwrite changed content. `archive.json` maps original
paths to archived paths. The copied `Makefile_internal.inc` has a `.frozen`
suffix because TFLM recursively discovers that exact basename even under ignored
directories.

The ignored archive must be retained or backed up separately from Git. The lock
describes this workspace's original measured binaries and captures, including
their provenance. A checkout without those artifacts must recover the archive
or establish a separately reviewed baseline; the freeze command fails rather
than fabricating a passing gate from missing measurements. The tracked 1,000-byte
output fixture and compact tensor golden hashes remain available in Git.

## Native tensor oracle

`tools/compiler/oracle.cc` is a separate host application with the same model,
eight operator registrations, and pinned reference kernels as B0. Its make
fragment is supplied with a second `-f` argument. Its objects, library, and
executable live exclusively under `build/compiler/tflm-oracle/`; no dependency
source files or B0 application sources are edited. The oracle build enables
`WERROR=1`.

The oracle enables TFLM's `preserve_all_tensors` option and snapshots each
operator's outputs in the profiler completion callback. It validates callback
types and order against the actual model using the pinned schema compatibility
helper. This includes the model's deprecated opcode representation. Tensor
snapshots retain original node/tensor IDs, operator, dtype, shape, byte length,
and raw bytes. Flushing metadata after each node preserves the completed prefix
if a subsequent reference kernel aborts.

The oracle reserves a static 16 MiB host arena and uses 7,445,488 bytes with
preservation enabled. This debugging allocation is not a proposed target memory
plan or a CV-Wally RAM requirement. `--no-preserve` runs the same reference
application without capture callbacks and with the original 2 MiB arena; tests
check its 1,688,176-byte usage and compare successful full outputs byte-for-byte.
File I/O and capture overhead make the oracle unsuitable for performance claims.

The Python capture runner records compiler/build flags, source and executable
hashes, library hash, model hash, TFLM revision, Git revision/dirty state, and
per-file hashes. There are no generated timestamps. Captures are stored under
`build/compiler/oracle/<provenance-hash>/`, with `latest.json` pointing to the
current capture. Existing captures are verified and retained. The normal build
does not update golden fixtures.

```sh
python3 tools/capture_tflm_oracle.py verify build/compiler/oracle/<capture-id>
python3 tools/capture_tflm_oracle.py compare <reference-capture> <candidate-capture>
```

Comparison reads complete arrays and reports the first divergent node, tensor,
and byte. The committed golden hashes independently detect changes to any
captured node. The baseline output is also preserved as a complete binary fixture.

## Input coverage and reference limitation

| Case | Public UINT8 bytes | Recorded outcome |
|---|---|---|
| baseline | B0 LCG, seed 1 | All 64 nodes and 1,000 output bytes |
| zeros | All 0 | Complete |
| maximum | All 255 | Complete |
| zero_point | All 131, representing real zero | Reference SIGABRT in Softmax at node 62; nodes 0–61 preserved |
| alternating | Alternating 0 and 255 | Complete |
| ramp | Repeating 0–255 | Complete |
| random_42 | LCG, seed 42 | Complete |
| random_deadbeef | LCG, seed `0xdeadbeef` | Complete |

There are **seven complete full-model references and 510 complete node tensors**
across eight scenarios. Python and C++ independently reproduce the entire
baseline input, and tests verify every byte of both quantization boundary
conversions. Representative full outputs include nodes 1, 4, 8, 15, 58, and 61.

The zero-point failure also reproduces without tensor preservation, using the
normal memory planner and 2 MiB arena. The native crash backtrace identifies
`reference_ops::Softmax<int8_t, int8_t>`; the pinned implementation contains an
unconditional exponent-range check. This is a reference limitation to investigate
in Stage 2, not a successful full-model fixture. No output is invented, no check
is removed, and no upstream numerical code is patched. Tests require the recorded
failure and completed tensor prefix explicitly. An independent runtime's handling
of this input must be resolved in the numerical-contract stage before claiming
parity across all valid inputs.

## Measurement boundary and handoff

B0 counts `MicroInterpreter::Invoke()` from function entry through the returning
instruction, including its callees and excluding the caller's call. The future
generated path will use one stable, non-inlined inference entry enclosing the
entire graph, including both quantization boundaries and required tensor copies.
Its measured interval will likewise run from entry through return. Input
generation/loading, parameter preparation, checking, capture/file I/O, and
printing remain outside. Any node instrumentation used in a measured build must
have its overhead identified separately. Spike retirements remain instruction
measurements, not RTL cycles.

Stage 0 verification reproduced the native/Spike checksum `0x4b6a91e2`, passed
all 14 compiler tests and all five existing profiler tests, and reproduced
4,867,278,370 inference instructions with 4,820 interpreter overhead. Both new
event files and both new PC histograms equal the original B0 files byte-for-byte.
The detailed local handoff is `build/compiler/stage-0-report.md`.

## Stage 1 graph IR and validation

`compiler/frontend.py` decodes the FlatBuffer into frozen dataclasses in
`compiler/ir.py`. `compiler/validation.py` checks the supported numerical metadata,
operator options, shapes, and topology. `compiler/export.py` writes the generated
artifacts. No target code or arena addresses are produced.

The default output is `build/compiler/import/`:

- `graph_ir.json`: canonical schema-version-1 IR with all 166 original tensor IDs,
  64 node IDs, eight versioned operator codes, and 165 original buffers. Nonempty
  buffers retain their complete bytes as hex plus SHA-256 and byte length.
- `nodes.md`: the 64-node table, named operands, output shapes, and inferred
  padding in top/bottom/left/right order.
- `graph.dot`: actual tensor-to-operator and operator-to-tensor edges, including
  all nine residual ADD paths. Constant tensors are distinguished visually.
- `manifest.json`: source/model hashes, pinned dependencies, Git revision/dirty
  state, actual pass list, artifact hashes, and explicit capabilities. Kernel,
  memory-plan, and ELF hashes remain null.

The IR retains tensor names, shape signatures, original buffer IDs, dtypes,
layouts, scale/zero-point arrays, quantized axes, calibration min/max metadata,
and producer/consumer IDs. Constant decoding uses explicit little-endian signed
INT8/INT32 or unsigned UINT8 formats. Both public UINT8 conversions remain nodes
0 and 63. The 101 constant tensors contain 4,697,032 bytes; runtime tensors sum
to 7,254,424 bytes without reuse. These are size inventories, not arena plans.

Optional biases remain named operands with null tensor IDs; original input
vectors retain the distinction between omitted trailing operands and explicit
`-1` operands. Reshape remains a runtime output with a validated constant target
shape; no aliasing decision is made. Reused empty FlatBuffer buffer IDs, including
buffer 0 for public input/output, do not imply shared runtime storage.

Every supported builtin option is decoded, including stride/dilation, padding,
depth multiplier, fused activation, ADD's INT16 flag, FC flags/weight format/bias
type, Softmax beta, and Reshape's optional shape vector. Legacy absent
QUANTIZE/RESHAPE tables are handled explicitly. Opcode normalization follows
pinned TFLM's `GetBuiltinCode` maximum-of-legacy-and-modern-fields rule; the raw
fields are also retained. Positive concrete shapes remain authoritative for the
legacy model whose `has_rank` fields are false.

Shape inference checks channel compatibility, SAME/VALID output dimensions and
asymmetric padding, residual shapes, FC dimensions, pooling, both conversion
boundaries, and Reshape element counts/targets. Quantization checks include finite
positive scales, valid scale/zero-point counts and axes, symmetric weights,
asymmetric activation zero-points, INT32 biases with compatible scales, and
the required INT8 Softmax output representation. Bias scale consistency uses the
existing audit's relative tolerance of `1e-5`; the original float32 values are
retained exactly. Prepared integer multipliers, shifts and rounding contracts are
explicitly pending Stage 2.

The public CLI additionally requires the exact model hash/size, graph and dtype
counts, operator versions, and public I/O from the tracked audit. The lower-level
import function accepts only the small supported subset used by synthetic tests.
It rejects custom/control-flow operators, unsupported versions/options, dynamic
shapes, malformed references, multiple producers, forward/cyclic edges, bad
buffers, floating/variable/sparse/variant tensors, external payloads, and model
metadata/signature extensions. Shape-changing broadcasting, grouped convolution,
FC packing/nondefault dimension flags, and general requantization operators are
outside this subset. The structural reader bounds-checks supported tables and
vectors and rejects populated unknown fields. Nothing quietly falls back to
floating-point execution or another runtime.

Canonical IR is independent of input/output directory paths and timestamps.
`Graph.from_json` validates serialized constants and derived graph/padding
metadata on round-trip. All 35 frontend tests pass, including source FlatBuffer
fixtures for each operator, malformed/unsupported cases, all nine residual edges,
all original tensor data/quantization, and output metadata agreement with Stage
0's oracle. See `build/compiler/stage-1-report.md` for the current gate evidence.

Stage 2 will extract and compare pinned TFLM's prepared integer parameters and
resolve numerical contracts. The recorded all-131 Softmax failure remains open
for that stage. Stage 1 stops before code generation, optimization, and memory
allocation.
