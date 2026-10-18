# Fixed-model compiler

The compiler is a controlled comparison with the unchanged LiteRT Micro B0.
Stage 0 supplies a frozen reference, native tensor oracle, deterministic inputs,
and tests. Stage 1 imports and validates the fixed TFLite graph, preserves its
constants, and exports typed graph IR. Stage 2 prepares integer parameters and
checks them against pinned TFLM. Stage 3 plans static tensor/scratch storage and
proves alignment, lifetimes, and safe Reshape views. Stage 4 emits and validates
standalone A0 reference inference. Optimizing kernels belongs to later
stages of the [design guidelines](../tools/compiler/CUSTOM_COMPILER_DESIGN_GUIDELINES.md).

**Accepted software B1:** the standalone 2×2 spatial pointwise configuration is
the software baseline for subsequent ISA experiments. The
[B1 implementation and profiling report](B1-software-report.md) explains each
optimization and compares fresh repeated profiles against corrected A0, initial
B1, previous B1 and frozen B0. Use `gmake compiler-b1-software-build`,
`gmake compiler-b1-software-verify` and `gmake compiler-b1-software-checkpoint`;
these pass the full accepted selection explicitly. Historical B1 defaults remain
available for reproducing earlier experiments.

**Stage 7 X1:** `--config X1` selects the accepted B1 defaults and replaces eligible
pointwise reductions with Xqmac8. Use `gmake compiler-x1-build`,
`gmake compiler-x1-verify`, `gmake compiler-x1-tests`, and
`gmake compiler-x1-checkpoint`. See the [ISA contract and measured report](xqmac8.md).

Compiler profiling is now a separate pre-Stage-5 workstream. See
[compiler profiling and evidence](compiler-profiling.md) for immutable build
snapshots, repeated A0 profiles, isolated kernel replay, verified GCC analysis,
offline reports, checkpoint gates and implemented schema-v2 viewer integration.

The pre-implementation project snapshot is commit `02e58f3`. The public compiler
commands accept the exact model identified by the tracked audit:

| Command | Behavior |
|---|---|
| `import MODEL --output-dir DIRECTORY` | Validate and export JSON IR, node table, DOT graph, and manifest |
| `validate MODEL` | Check the supported graph/quantization/shape contract and frozen model identity |
| `inspect MODEL` | Print the validated per-node table |
| `plan-memory MODEL --output-dir DIRECTORY` | Export validated memory plan, kernel memory contracts, lifetime data, collision audit and manifest |
| `generate MODEL --config A0 --output-dir DIRECTORY` | Emit standalone reference C++17, constants, plans, source map and provenance |

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

`compiler-tests` builds both oracles, numeric wrappers, and A0 native/diagnostic/
sanitized/RV64 executables. It verifies the complete input suite, prepared
parameters, memory plan, standalone node arrays, and Spike output, then runs all
five stages' tests. To run earlier steps individually:

```sh
gmake compiler-oracle-build
gmake compiler-oracle
gmake compiler-prepare
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
unconditional exponent-range check. Stage 2 diagnoses exponent 32 below; this
remains a failed full-model fixture. No output is invented, no check
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
retained exactly. Prepared integer multipliers, shifts and rounding contracts
live in the separate Stage 2 IR below; the Stage 1 artifact stays unchanged.

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

Stage 1 stops before parameter preparation, code generation, optimization, and
memory allocation.

## Stage 2 integer preparation and contracts

```sh
gmake compiler-prepare
gmake compiler-quantization-tests
gmake compiler-numeric-sanitize
```

`compiler/quantization.py` independently computes integer parameters offline.
`tools/compiler/prepared.cc` wraps each actual pinned registration's Prepare
callback, then reads the initialized, numerically relevant fields from its real
`user_data`. It only calls `AllocateTensors()`, never inference. No dependency
source is patched. The dedicated executable shares the Stage 0 oracle's isolated
library and object directory; the original B0 objects are separate.

The real model compares **42,598 integer values across all 64 nodes**, including
every Conv/Depthwise output channel, FC's scalar scale, all three ADD scales and
offsets, fused clamps, asymmetric padding and its offsets, both QUANTIZE scales,
and Softmax scaling/radius. RESHAPE has no prepared numerical fields. Unused or
uninitialized fields, pointers, and scratch allocation indices are deliberately
excluded. Synthetic source FlatBuffers also exercise each operator, missing
bias, all four supported fused activations, and the FC binary32 scale-product
rounding detail. Parameter equality uses complete key sets and exact integers,
including each array element.

`build/compiler/prepared/` contains `prepared_ir.json`, the actual `oracle.json`,
and a provenance manifest with source/reference/binary hashes, compiler versions,
resolved commands/flags, graph hash, and parity evidence. The prepared IR links
to Stage 1's canonical graph hash and holds offsets, effective bias scales,
per-channel accumulator bounds, eligible corrected biases, padding policies,
and the arithmetic contract. Its capability fields leave memory planning and
inference generation disabled. `PreparedGraph.from_json(text, graph)` revalidates
all derived data against the source graph. Neither canonical IR contains paths
or timestamps.

The numerical contract is the pinned **double-rounding** path:

- Offline multipliers use binary64 `frexp` with nearest rounding, ties away from
  zero, a carry at `2**31`, and flush to zero below shift -31. FC computes its
  input/weight scale product in binary32 before conversion to binary64; Conv and
  Depthwise multiply those scales in binary64. Activation quantization divides
  in binary32 before rounding.
- Requantization checks the left-shifted INT32 input, uses the saturating doubling
  high multiply (ties toward positive infinity), then rounding division by a
  power of two (ties away from zero). Add output zero-point, apply the fused
  clamp, then narrow. Python uses explicit truncation/floor rules and wide
  integers. Reused C++17 headers require arithmetic right shift, verified with a
  compile-time assertion. No INT32 overflow or wrapping is permitted in the
  accumulator/requantization contract.
- ADD preserves both asymmetric input offsets and distinct scales, with a fixed
  left shift of 20. AveragePool rounds the sum of valid quantized taps to nearest,
  ties away from zero, and excludes padded positions from its divisor. Both
  public QUANTIZE nodes preserve their UINT8/INT8 128 representation shifts.
- Softmax reuses pinned Q5.26 exponential, Q12 accumulation, reciprocal, and
  output rounding helpers. Row maximum, sum, reciprocal, and exponent depend
  on runtime input; they are never frozen as prepared constants.

For every real Conv/Depthwise/FC channel, wide offline bounds prove INT32 safety
for every accumulation prefix, bias addition, requantization left shift, and
output offset over the entire legal INT8 activation range. Conservative bounds
reject unsupported graphs rather than assuming overflow behavior. For unpadded
1x1 Conv only, the IR additionally records checked
`bias + input_offset * sum(weights)`. The raw dot-product prefixes with that
corrected bias are also bounded. This is a proof/data artifact for later stages,
not an enabled optimized kernel. Padded Conv/Depthwise retain valid-tap skipping;
a full-filter bias correction is only equivalent if explicit padding contains
the input's quantized zero. Directed native border tests demonstrate this and
the incorrect result from applying the full correction to skipped taps.

`kernels/reference/numerics.{h,cc}` exposes standalone checked wrappers for
requantization, ADD, AveragePool, boundary conversion, and Softmax, plus small
dot/border test adapters. The wrappers have no interpreter or allocator dependency.
`tools/prepare_compiler.py` records the native build and checks it before capture
or testing. Sanitizer builds compile both the wrappers and the used out-of-line
requantization source with ASan/UBSan; linked oracle library code is not covered
by that sanitizer claim. On macOS the sanitizer build defaults to the installed
Command Line Tools clang, with `COMPILER_SANITIZER_CXX` as an override. This avoids
the older selected Xcode ASan runtime's observed startup deadlock on macOS 27;
B0 and the reference oracles keep their original compiler configuration.

The all-131 reference failure is now diagnosed exactly: node 62's Q12 exponential
sum is **305,171,598**, producing **exponent 32** where pinned INT8 Softmax requires
0 through 31. The checked standalone wrapper returns status 2 and leaves its
output untouched; it does not fabricate a probability tensor. All seven complete
reference Softmax arrays match byte-for-byte. The original B0 and its recorded
SIGABRT remain unchanged. A later full runtime must carry this input-domain
failure explicitly or obtain a separate decision about a reference fix.

Stage 2 stops before memory planning or generated inference. Its actual test
counts, hashes, gate checklist, and reproducible evidence are recorded in
`build/compiler/stage-2-report.md`.

## Stage 3 static memory planning

```sh
gmake compiler-memory-plan
gmake compiler-memory-tests
# Example explicit workspace budget and stack reserve (not measured stack):
gmake compiler-memory-plan \
  COMPILER_MEMORY_FLAGS='--workspace-budget-bytes 2097152 --stack-reserve-bytes 4096'
```

For offline use after the pinned sources are available, the CLI can prepare
parameters itself without compiling or invoking TFLM:

```sh
uv run --python 3.12 --with-requirements tools/compiler/requirements.txt \
  python -m compiler plan-memory models/efficientnet-lite0-int8.tflite \
  --output-dir build/compiler/memory
```

The Make target first verifies the Stage 2 native parameter oracle and supplies
its prepared IR. Both paths revalidate the graph and prepared parameters. The
public CLI still locks the exact audited model. Synthetic tests use only the
supported lower-level graph API.

`compiler/kernel_plan.py` introduces only the memory portion of a kernel plan:
node/implementation identity, input access and alignment, output alignment,
node-local scratch and its resolved condition, Reshape view support, and stack
policy. The default selected contracts describe the pinned reference INT8 paths.
Those paths require **zero arena scratch**: INT4 unpacking/compression branches
and INT16 Softmax LUTs are outside this compiler's validated subset. Persistent
TFLM OpData/allocation indices are interpreter setup metadata; they are not AOT
scratch. Prepared integer payloads live in read-only storage. No optimized
algorithm or in-place ADD/Conv implementation is introduced. Alternate access,
alignment and scratch contracts in tests exercise the planner's safety rules;
they do not imply executable implementations of those variants.

`compiler/memory_plan.py` uses inclusive epochs: -1 for input setup, 0–63 for
whole kernel calls, 64 for output handoff. Each runtime tensor records producer,
earliest use, last consumer, and its storage lifetime. An output cannot reuse an
input at the same node. Skip tensors remain live through their last residual
consumer (for example tensor 107 runs from producer 6 through consumer 10).
Public inputs are initialized before invocation and can be reused after their
last read; `--preserve-inputs` keeps their storage through handoff instead.
All public outputs remain live through handoff and are valid until the workspace
is used again. Unused graph inputs still occupy storage during input setup.

Reshape aliases are permitted only with an explicit view contract, identical
flat byte representation/quantization, a runtime source, and read-only accesses
throughout the alias group. The physical group takes the union of lifetimes and
the strictest alignment of all members and consumers. This handles transitive
and branching views without releasing storage at the source's earlier last use.
Mutable consumers, immutable sources, or `--copy-reshape` force separate storage
and a future copy. Other input/output aliasing is conservatively disallowed.

The deterministic allocator sorts physical groups by descending size, then
lifetime and stable identity, and chooses the lowest aligned fitting offset.
Scratch uses the same workspace, remains live for its entire node, conflicts
with that node's inputs/outputs and other scratch, and can share dead storage
or scratch from other nodes. Disabled scratch gets no storage. Zero-byte
requests have no address; zero-sized model tensors remain explicitly rejected
by the existing positive-shape frontend contract.

An independent validator checks every overlapping-lifetime physical buffer pair,
bounds, alignment, reconstructed source lifetimes, Reshape proofs, read-only
intervals, and budgets. Serialized plans are revalidated against the original
graph, prepared parameters and memory contracts. Tests also use an independent
byte/epoch occupancy oracle across 100 randomized problems (2,500 requests).

Current real-model result:

| Storage | Bytes |
|---|---:|
| Runtime tensor bytes summed without reuse | 7,254,424 |
| Peak live activations / planned workspace | **1,505,280** |
| Arena scratch for these reference INT8 contracts | 0 |
| Constant tensor payload | 4,697,032 |
| Defined INT32 prepared parameter payload | 170,392 |
| Read-only layout including alignment | 4,867,424 |
| Measured stack / total target RAM | Pending Stage 4 |

The workspace base requires 16-byte alignment; tensor alignment also follows
operand/type requirements. Tensor 161 views tensor 160 across nodes 59–61.
For this graph the plan equals the peak-live lower bound, with no extra
alignment/fragmentation capacity. This is a storage proof, not an executed model.

B0's **1,688,176 bytes** is its **total TFLM arena**, including persistent
interpreter metadata. The AOT activation/scratch figure uses different
accounting; it does not establish a measured runtime-memory improvement.
Constant weights/INT32 biases/shape data and prepared parameters are planned in
`.rodata`, activations/scratch in `.bss`, and stack separately. The defined
parameter layout is sorted contiguous little-endian INT32 fields/arrays, not
a host `sizeof(OpData)` estimate. Unselected Stage 2 corrected biases are not
allocated. Shape/option tables, code, linker padding, platform data, and compiled
stack peak remain Stage 4 work, so the read-only layout is not a final ELF size.

`--workspace-budget-bytes` and `--rodata-budget-bytes` enforce explicit limits.
Failures identify required/available bytes before writing new artifacts.
Without a workspace limit the report warns that physical target capacity is
unverified. `--stack-reserve-bytes` records a caller budget alongside workspace;
it does not claim a measured peak or a full RAM guarantee. No default budget is
inferred from Spike's 128 MiB linker map or an unknown CV-Wally memory capacity.

Exports in `build/compiler/memory/` are `memory_plan.json`,
`kernel_memory_contracts.json`, `memory_lifetimes.json`, `collision_check.json`,
`memory_report.md`, and `manifest.json`. Canonical data/plan artifacts are
independent of output paths and timestamps. The manifest records source and
pinned reference-kernel hashes, graph/prepared/contract/plan hashes, options,
checks, and explicit capability limits. `build/compiler/stage-3-report.md`
contains the actual gate results and reproduction evidence.

Stage 3 stops here. It does not generate inference, optimize kernels, measure
Spike performance, or change the known pinned Softmax input-domain failure.

## Stage 4 standalone A0 reference model

```sh
gmake compiler-generate
gmake compiler-a0-verify
gmake compiler-codegen-tests
```

`A0` is the standalone reference diagnostic configuration. B0 continues to run
the original pinned LiteRT Micro interpreter. Stage 5 adds the explicit B1
configuration described below; custom instructions remain later work.

`compiler/lowering.py` validates the Stage 1 graph, Stage 2 arithmetic and Stage 3
storage proof and accepts only the reference memory/kernel contracts.
The Make target supplies the saved `--prepared-ir` and `--memory-plan` artifacts;
generation revalidates and uses their addresses and aliases, including any
`COMPILER_MEMORY_FLAGS` choices. Direct CLI generation may instead compute the
validated defaults offline when those artifact arguments are omitted.
`compiler/emit_cpp.py` and tracked templates emit readable C++17 with one stable
`a0_node_NN` wrapper per original node and one `a0_invoke` entry that calls all 64
in the fixed order. Operators call the pinned reference integer Conv, Depthwise,
FC, ADD, pool and Requantize implementations directly. Reshape uses its proven
view or copies when the supplied valid memory plan requires it. This path links
neither a TFLM interpreter/allocator nor a FlatBuffer reader/runtime library.

Constants are typed INT8/INT32 fields in a static aggregate, with offset/size
assertions against Stage 3's read-only layout. Prepared arrays preserve original
channel order; biases remain unadjusted. Runtime storage is a statically sized
INT8 array with compile-time extent/alignment checks for each tensor and guards
immediately before/after the workspace. UINT8 I/O accesses its byte representation;
INT32 weights/parameters never use casts from an unaligned byte arena. No heap
allocation occurs during inference. The host capture harness may allocate its
file-input vector outside inference; the bare-metal ELF is screened for heap
allocator symbols as well as interpreter symbols.

Public input is UINT8 `[1,224,224,3]` and output is UINT8 `[1,1000]`. Both boundary
QUANTIZE nodes and the exact B0 LCG sequence remain present. Input setup resets
guards and invalidates old output; input is consumed by invocation and must be
set again before another call. Output is exposed only after success. Invalid
state returns 3. The diagnosed all-131 Softmax case returns 2 at node 62 without
exposing an output, retaining all 62 successfully produced prefix tensors in
diagnostic builds. This is an explicit representation of B0's known domain
failure, not a fabricated probability tensor or a patch to B0. The pinned
fixed-point Softmax is reused via Stage 2's checked wrapper, including an extra
exp/sum preflight to avoid the reference abort. That work remains inside A0's
inference interval and must be included in any later performance comparison.

Generated artifacts live in `build/compiler/A0/`: `constants.{h,cc}`, `model.{h,cc}`,
`source_map.json`, all three prior IR/plans, kernel memory contracts, and a
generation manifest. Canonical sources and source maps contain no output paths
or timestamps. Source-map entries retain original node/tensor IDs, generated
symbol, exact source line, and output arena offset. Typed arrays and normal GCC
produce executable code; the generator does not emit machine instructions.

`tools/build_a0.py` compiles four isolated variants without the microlite library:

| Variant | Purpose |
|---|---|
| `native` | Optimized native build with capture hooks compiled out |
| `capture` | Native full-output snapshots at node completion and per-node guard checks |
| `sanitized` | Capture build with ASan/UBSan covering generated execution and arithmetic source |
| `rv64` | Bare-metal `rv64imc/lp64`, no capture hooks, debug/source symbols retained |

The native variants use the selected host compiler; the sanitizer uses the
installed newer Command Line Tools clang by default as in Stage 2. RV64 uses
the pinned xPack GCC and the existing unmodified startup, HTIF syscalls and
linker script. It starts through `_start`, initializes gp/sp and BSS, and exits
through HTIF. `tools/compiler/a0_target.cc` uses the console directly, without
assuming hosted file I/O or startup constructors. Each build records resolved
commands, flags, environment, generated/source/helper hashes, binary hash and
the 64 stable node symbols. RV64 additionally records linked sections, map,
compiler stack-usage files and the original ISA audit.

The full verification compares every byte of **510 available node arrays per
capture variant** (seven complete 64-node cases and the failed case's 62-node
prefix) against the pinned TFLM oracle. Native release outputs also match all
seven public arrays and the known error case. ASan/UBSan covers the complete
model, not just scalar helpers. Guard corruption, short/oversized inputs,
post-error recovery and reused workspace, deterministic generation, first
divergence reporting, source-map identity, and a copied-Reshape/128-byte-aligned
variant are checked. Spike output includes all 1,000 bytes in hex so comparison
is stronger than the B0 smoke-test checksum alone.

The release `a0_invoke` boundary encloses the fixed computation and node call/
status overhead. Input preparation, file output, checksums, guard verification,
and stack painting/reporting occur outside that boundary. Diagnostic callbacks
and per-node guard checks are compiled out of native release and RV64. Empty
Reshape retains an observable wrapper via a compiler barrier, which emits no
instruction but preserves call/return overhead. No A0 instruction-count speedup
is claimed at this stage, and A0 must not be labeled B1.

Memory accounting distinguishes Stage 3's 1,505,280-byte activation workspace
from actual linked `.bss` (also guards/state), `.rodata` (also shape metadata and
application literals), code and HTIF data. Compiler `.su` reports are individual
frames and may include linker-discarded functions; they are not a full call-chain
peak. Stack painting measures the baseline run with an untouched safety gap;
it does not prove a universal stack requirement over all inputs. The existing
1 MiB stack reservation and 128 MiB linker map are simulator provisions, not
CV-Wally physical RAM claims. Exact linked sizes, stack evidence, hashes, actual
test counts and PASS/FAIL/BLOCKED gates are in `build/compiler/stage-4-report.md`.

Stage 4 stops before B1 scalar specializations or ISA extensions.

The compiler preparation checkpoint adds `kernel_plan.json` as the authoritative
selection record. Each selection identifies its implementation, reduction and
requantization backends, static geometry, scalar parameters, weight layout,
optimization choices and memory contract. Corrected-bias eligibility and shift
range facts describe available proofs; the reference selection does not enable
those kernel optimizations. The memory planner consumes the selected contracts;
emission validates the supplied plan instead of replacing it with reference
defaults. `generate --kernel-plan <file>` accepts a previously emitted plan and
rejects unsupported implementations, backends or altered facts before writing
output. Static helper limits, including Softmax depth <= 1,000, are checked during
selection. Input-dependent Softmax diagnostics remain unchanged.

Generated shapes use explicit dimension assignments so GCC can specialize them
under the existing bare-metal `-fno-builtin` flags. Prepared scalar parameters
are emitted as literals, while weights and per-channel arrays remain read-only
data. The constant aggregate declares the memory plan's base alignment. Existing
reference algorithms, boundary conversions, wrappers and Softmax preflight remain
in place. This is a separately measured A0 metadata checkpoint, before B1 kernels;
the earlier A0 ELF and profiles remain available in their immutable snapshots.

One compilation context verifies preparation once and retains independent
canonical snapshots of graph and prepared data. Emission and memory validation
check those snapshots, including nested parameter dictionaries, so reused work
cannot hide mutations or stale supplied parameters. Memory allocation and its
independent interval/collision audit share the same validated problem rather than
recomputing numerical preparation. External serialized plans retain validation.

The generation manifest binds the kernel-plan hash, and execution units preserve
their exact selections. Capture/report and replay verify those links using the
saved artifacts, without selecting kernels again from the working tree. Historical
captures predating kernel plans remain readable. See
`results/profiling/A0-static-metadata/` for the repeated production-ELF measurement
and comparisons with original A0 and B0.

## Stage 5 first checkpoint: scalar pointwise kernels

The current A0 profile attributes 74.1% of retirement instructions to its 32
pointwise convolutions, 18.1% to depthwise convolutions, and 7.0% to the stem.
This first B1 checkpoint replaces only the pointwise paths. Stem unrolling,
depthwise specialization, output-channel blocking and custom instructions remain
separate experiments.

```sh
gmake compiler-b1-tests
gmake compiler-b1-checkpoint
```

`python -m compiler generate <model> --config B1` defaults to
`build/compiler/B1`; A0 still defaults to `build/compiler/A0`. Both configurations
use the same `tools/build_a0.py` build/compare driver and the same public ABI
(`a0_invoke`, `a0_node_NN`). Build, execution, source-map, replay and capture
metadata record the actual configuration independently of checkpoint labels.

`kernels/rv64imc/pointwise.h` implements scalar NHWC/OHWI pointwise convolution
with eight sequential products per reduction group and pointer-based row access.
Only stride-one, dilation-one, unpadded 1x1 kernels with complete groups of eight,
matching spatial geometry and proven corrected biases are selected. Other nodes
retain the pinned reference path. Selection is based on geometry and numerical
proofs, never hard-coded node numbers. Unknown or altered implementations,
backends and optimization choices are rejected before emission.

The offline identity is `corrected_bias = bias - input_zero_point * sum(weights)`.
The existing preparation proof checks `abs(corrected_bias) + 128*sum(abs(weights))`
against INT32 limits, covering bias-first accumulation and every scalar prefix.
Corrected biases are allocated as explicit read-only prepared arrays; original
weights and biases are retained. Allocation and emission consume the same
selected parameter payload. This increases read-only storage and does not change
the activation arena or require scratch storage. Requantization, rounding,
activation clamps and Softmax diagnostics retain the pinned reference semantics.

The eight-lane scalar `dot8` uses ordinary INT8 loads and INT32 products, with
selective unrolling under the existing `-O2` build. It provides a defined boundary
for a future packed backend without introducing custom instructions in B1.
Code size, load/store counts and per-node retirements must be checked in the
linked RV64IMC ELF. Isolated replay uses the same generated wrappers and verified
oracle inputs; full invocation measurements remain the acceptance evidence.

`compiler-b1-checkpoint` builds native, capture, sanitized and RV64 variants,
compares all oracle cases, audits the ISA, runs ordinary Spike, and requires two
identical full profiles. Its parent defaults to the preserved A0 static-metadata
capture; set `B1_PARENT_CAPTURE` explicitly when restoring that ignored artifact
on another machine. Compact measurements are saved to
`results/profiling/B1-pointwise/`; immutable binaries, snapshots and raw captures
remain under ignored build storage.

## B1 stem unrolling checkpoint

The next opt-in checkpoint retains the pointwise kernel and enables the measured
function-local GCC unrolling choice for the RGB 3x3, stride-two, dilation-one
reference convolution. Selection uses geometry rather than node number. The
arithmetic implementation, quantization helpers, borders and memory contracts
remain unchanged. No global optimization flags change.

```sh
gmake compiler-b1-stem-checkpoint
```

This target writes `build/compiler/B1-stem/`, compares against the preserved
pointwise-only capture, and saves compact results in
`results/profiling/B1-stem-unroll/`. It uses `--config B1 --stem-unroll`;
`--config B1` without that option retains the pointwise-only selection.
`B1_STEM_PARENT_CAPTURE` overrides the parent when restoring artifacts elsewhere.

The kernel-plan choice `gcc_rv64_function_unroll_loops` requests
`__attribute__((optimize("unroll-loops")))` on the selected wrapper. Its macro is
active only for RV64 GCC; native Clang builds verify the same reference arithmetic
without an unsupported target attribute. The normal compilation level remains
`-O2`. The choice is preserved in the execution unit's saved selection, so the
viewer can show it under operand memory requirements and choices.

Saved plans restore their recorded option without needing to repeat the CLI
flag. An explicit request that conflicts with a supplied plan is rejected, as
are unimplemented, duplicated or misplaced choices. A0 rejects this option.
Constant payloads and the activation/scratch memory plan match the pointwise-only
build. Every changed code-generation selection still requires fresh native,
sanitized, isolated RV64 and repeated full-inference evidence before acceptance.

## B1 pointwise output-channel blocking

The next checkpoint compares output-channel blocks of two and four against the
same B1 stem-unrolling capture. OC4 wins all 32 pointwise units by retirement
count; OC2 remains selectable as the smaller-code alternative.

```sh
gmake compiler-b1-blocking-checkpoint  # accepted OC4 schedule
# Independent alternative:
gmake compiler-b1-oc2-checkpoint
```

`generate --config B1 --stem-unroll --pointwise-block 2|4` selects a fixed scalar
schedule. Omitting `--pointwise-block` retains block one. The new checkpoint
recipes use separate `build/compiler/B1-oc2/` and `B1-oc4/` directories, label their
captures independently and compare both against the same preserved stem parent.
`B1_OC_PARENT_CAPTURE` overrides that parent when restoring artifacts elsewhere.

`pointwise_dot8_blocked` maintains two or four independent corrected-bias
accumulators. Within each eight-element input group, it loads an activation once
and reuses it across output channels. OHWI weights, reference per-channel
requantization, eight-lane grouping and numerical prefix proofs are unchanged.
The outer schedule takes a static reduction-policy type; the current
`ScalarDot8Block` uses only normal RV64IMC byte loads, multiplies and additions.
A later Xqmac policy can retain this schedule, with its encoding, signed arithmetic,
packed-load alignment and overflow semantics separately specified and tested.
No packed loads, weight repacking or custom instructions are introduced here.

The compiler selects `rv64imc/pointwise_dot8_oc2/int8` or
`rv64imc/pointwise_dot8_oc4/int8` only for the existing eligible pointwise geometry
and output-channel counts divisible by that block. Nondivisible output channels
retain the block-one path; unsupported reductions retain the reference fallback.
There is no unchecked partial block. Each execution unit records its selected
block, backend and memory contract. Constants and physical tensor/parameter
placements remain unchanged; the memory-plan identity changes with its kernel
contract identity. Accumulators are fixed stack/register locals, with no scratch
or heap allocation.

Saved kernel plans support independently validated per-unit block choices and
round-trip without repeating the global CLI flag. Explicit conflicting requests,
unsupported blocks and overrides of non-pointwise nodes fail before emission.
The compiler does not perform runtime tuning or select code from checkpoint
labels. Source generation emits the chosen template specialization and profiling
reports its inclusive measured cost.

The comparison and gates are in `results/profiling/B1-blocking/`; individual full
captures, isolated replay and GCC summaries are under `B1-oc2*` and `B1-oc4*`.
Full profiling remains separate from routine tests. Each candidate requires two
matching full captures, exact public output, node-wise native/sanitized equality,
RV64IMC auditing and reported code-size/load-store changes.

## B1 specialized depthwise kernels (Stage 6)

```sh
gmake compiler-b1-depthwise-checkpoint
# Independent filter-size selections against the same OC4 parent:
gmake compiler-b1-depthwise3-checkpoint
gmake compiler-b1-depthwise5-checkpoint
```

The accepted recipe retains stem unrolling and pointwise OC4, and adds
`--depthwise-kernels 3 5`. Each size is independently selectable; omitting this
option retains reference depthwise execution. Eligibility requires a square
3x3/5x5 INT8 1HWO filter, depth multiplier one, dilation one, and strides one or
two. Other geometry keeps the reference fallback. Selection uses static facts,
never logical node numbers or checkpoint labels. A0 rejects these switches.

`kernels/rv64imc/depthwise.h` splits the output into a statically bounded interior
and clipped border pixels. Interior reductions have fixed, unrolled tap offsets
and no padding tests. Borders clip valid tap bounds once per pixel, outside the
channel loop. Pointer construction stays inside valid input storage, including
inputs smaller than the filter and asymmetric SAME padding. Products retain the
reference row-major order, input zero-point correction on valid taps, bias after
reduction, and pinned per-channel requantization/activation clamps. Full-filter
corrected biases are deliberately not used at borders. There is no weight
repacking, scratch allocation, new custom instruction or global GCC flag change.

Saved plans restore both family selections and reject unknown or inconsistent
implementations, choices and geometry. The generation manifest records Stage 6
and hashes the runtime header; execution units expose the implementation and
choices in the existing viewer inspector. Constants, activation lifetimes,
physical placements and derived valid-product counts retain their parent values.
The memory-plan identity incorporates the new implementation contracts.

The checkpoint requires native, capture, sanitizer and RV64 correctness, ISA
auditing and two identical full captures. Nodes 8 and 15 are the initial isolated
replay cases; fixtures compare complete tensors, including every border byte.
Compact results are under `results/profiling/B1-depthwise*`; preserved build
snapshots and raw captures remain in ignored build storage. Performance is
reported as retired instructions, with code-size and memory-instruction costs;
hardware cycles and cache effects remain unmeasured.

The measured Stage 6 checkpoint retires **1,874,851,486 instructions**, 15.36%
fewer than OC4 (2,215,157,070). All 16 depthwise units improve, with other units
unchanged. Executable code increases by 12,736 bytes and the observed canonical
stack watermark rises from 416 to 536 bytes. Full dynamic memory instructions
increase by 9,417,956 despite the overall instruction reduction. See
[the independent-family comparison and acceptance evidence](../results/profiling/B1-depthwise-evaluation/README.md).

## Project-owned B1 runtime

The generated B1 program can build without the TFLM source checkout, headers,
`common.cc`, ruy or gemmlowp. This applies to the standalone target; B0, A0,
offline parameter verification and the independent oracle retain the pinned
reference implementation. Existing `tflm/platform/rv64imc/` startup, system calls
and linker script remain platform support in this repository.

```sh
gmake compiler-b1-numerics-checkpoint
gmake compiler-b1-project-kernels-checkpoint
gmake compiler-b1-standalone-checkpoint
```

These three explicit runtime selections preserve stem unrolling, pointwise OC4
and both specialized depthwise families. The default `--runtime reference`
retains the previous selections. `project-numerics` moves custom-kernel scaling
to the project scalar double-rounding helper. `project-kernels` also selects
project stem, FC, ADD, global average pooling, boundary conversion and Reshape
handling. `standalone` adds project Softmax and removes all target TFLM includes
and linked source files. Checkpoint labels never choose implementations.

The supported scope is the frozen model's INT8 operators, with explicit geometry
checks and rejection of unsupported project selections. The compiler does not
silently fall back to upstream kernels in standalone mode. The build driver
rejects any actual TFLM compiler dependency. Saved plans preserve runtime choices
and reject mixed, forged or conflicting selections. All previous reference paths
remain available for A0 and differential verification.

`kernels/project/` contains the project kernels, scalar numerical primitives,
Softmax, attribution and license. High multiplication, sign-sensitive rounding,
fixed-point exponential and reciprocal algorithms preserve the pinned reference
contract. The scalar implementation uses no custom instruction or packed loads.
Full-model correctness still includes boundary conversion and every intermediate
array. The checked Softmax sum is reused for output normalization, eliminating
the duplicate successful preflight work while preserving status 2 and untouched
output for the known all-131 exponent failure. No failed input is reported as a
successful performance result.

The FC kernel retains the input offset and uses eight-product scalar groups plus
an exact tail. The stem retains row-major valid-tap accumulation and reference
per-channel quantization. ADD uses equal shapes and precomputed scales; global
pooling retains signed integer rounding. Constant payloads and physical memory
placements are unchanged. There is no heap or arena scratch allocation.

Tests compare the new arithmetic and operators against independently compiled
upstream code under ASan/UBSan. A separate integration test builds with the
upstream location unavailable. The accepted RV64 snapshot is also rebuilt in a
workspace without a TFLM checkout, requiring identical loadable bytes. Full
profiles, replay, GCC analysis and viewer exports use frozen evidence as before.
See `results/profiling/B1-runtime/` for checkpoint comparisons and gate results.

The accepted standalone build retires **1,792,953,997 instructions**, 4.37% fewer
than the depthwise checkpoint, with 420 fewer executable bytes. All three runtime
checkpoints pass repeated full profiling and exact-output validation. See
[the runtime comparison and acceptance evidence](../results/profiling/B1-runtime/README.md).

## Reading generated source in the viewer

Generated B1 wrappers describe the logical node, tensor IDs, layouts, dtypes and
shapes before the kernel call. Each compile-time template value is labelled
(`InputChannels`, `PaddingTop`, `InputOffset`, and so on). Runtime operands are
listed separately, including the prepared multiplier/shift arrays. These labels
are comments; they do not create runtime shape objects or extra instructions.

`arena.data + N` is a byte offset in the planned activation arena.
`a0_constants.tN` is an original model constant tensor; `a0_constants.pN + K`
selects a prepared parameter block for node N, offset by K INT32 elements. Logical
operands may be replaced by prepared values: pointwise kernels read corrected
biases, while depthwise borders retain the original biases and apply the input
offset only at valid taps. The memory and execution inspectors preserve these
compiler-known relationships separately from runtime measurements.

The custom C++ headers use descriptive dimension, coordinate, accumulator and
pointer names. Comments explain NHWC/OHWI/1HWO layouts, border splitting, input
zero-point signs, output-channel reuse and quantization order. Softmax names
its Q5.26, Q0.31, Q2.29 and Q12.19 stages and documents normalization constants,
rounding points and the existing exponent diagnostic. These mathematical formats
count magnitude bits separately from the sign bit.

The readability checkpoint requires identical RV64 allocated sections and load
segments, unchanged kernel/memory plans, and two repeated full captures matching
the previous standalone checkpoint. Debug information and source line locations
are expected to change. Refresh the viewer bundle with the newly captured ELF
and GCC analysis so it displays the saved edited source.

## Software requantization specialization

`--requantization generic` preserves the general double-rounding helper and is
the default. Two explicit B1 options specialize project convolution kernels:
`nonpositive` calls a smaller out-of-line helper; `inline-nonpositive` permits
GCC to inline that arithmetic into each kernel. GCC may retain some calls in
the latter mode; the linked assembly and profiles record the actual result.
Both require project arithmetic (`--runtime project-numerics`, `project-kernels`
or `standalone`). Checkpoint names never select a policy.

Selection checks the prepared per-channel arrays: multipliers must be in
`[0, INT32_MAX]` and shifts in `[-31, 0]`. Only supported pointwise, depthwise and
project stem implementations with these proofs receive the specialized backend.
Other units retain their existing arithmetic. Saved plans reconstruct and verify
the selection, rejecting changed proofs, mixed markers and conflicting CLI
options. The execution-plan inspector exposes the numerical backend and policy
choice separately from the unchanged reduction backend.

For these multipliers, the exceptional `INT32_MIN * INT32_MIN` product cannot
occur. The reference high-multiply result is exactly
`(int64_t(x) * multiplier + (int64_t(1) << 30)) >> 31`, using the required
arithmetic signed right shift. For negative products, this is algebraically
equal to the reference negative nudge followed by division toward zero,
including halfway cases. The subsequent rounded right shift remains a separate
stage. No approximate single rounding or custom instruction is substituted.
The original generic, ADD and Softmax arithmetic remain available unchanged.

Prepared constants, bias corrections, reduction order, arena offsets and scratch
requirements are unchanged. GCC can still alter register allocation and code
size when it sees the specialized epilogue; compare both policies with repeated
full captures rather than assuming that inlining wins. The explicit checkpoint
targets are `compiler-b1-requantization-checkpoint` and
`compiler-b1-requantization-inline-checkpoint`. Numerical sanitizer tests compare
both helpers against the pinned upstream implementation on all 32 supported
shifts, extreme multipliers/inputs, directed rounding transitions and 6.4 million
random scale cases per helper.

`--requantization-inline-nodes NODE ...` explicitly overrides individual logical
nodes with the inline policy. Unsupported/unproven targets and duplicate IDs
are errors. The saved kernel plan preserves the default policy and each override;
reloading it does not consult a current profile or an ELF address. The selected
checkpoint (`compiler-b1-requantization-selected-checkpoint`) starts with the
out-of-line specialization and inlines only the 25 nodes that improved in the
two full-policy experiments. The selector has no model-specific node list;
the measured list is an overridable Make checkpoint configuration. New reduction
backends must remeasure these choices because register pressure can change.

The selected checkpoint retires **1,650,025,771 instructions (7.972% fewer)**,
with all 49 affected units improving. Memory instructions increase 0.473%, code
grows by 3,868 bytes and the canonical-input stack watermark rises from 536 to
584 bytes. [Comparison, costs and acceptance evidence](../results/profiling/B1-requantization-comparison/README.md).

## Spatial pointwise blocking

`--pointwise-pixels 2 --pointwise-block 2` or `4` selects a two-pixel scalar
pointwise tile. The reduction loads each OHWI weight once for two NHWC pixels;
each activation is shared across the output-channel block. The four or eight
independent INT32 accumulators visit channels in their original order. Channel
biases, multipliers and shifts are shared across pixels, while rounding and
clamping remain separate for every output. An odd final pixel uses the existing
one-pixel kernel with the same scaling policy. Flattened tiles may cross a row
or batch boundary because the supported unpadded 1x1 geometry is independent at
each pixel. The scalar backend still consumes eight input channels per group;
there is no packed instruction, weight repacking or extra arena scratch.

`--pointwise-tile NODE:PIXELS:CHANNELS` overrides a logical node's complete tile;
repeat the option for several nodes. Supported tiles are 1x1, 1x2, 1x4, 2x2 and
2x4. A full tile overrides the global defaults and API channel-only overrides.
Unsupported channel divisibility retains the existing one-pixel scalar fallback;
an input-channel reduction tail or unsupported geometry retains the reference
path. Saved plans record the actual implementation and odd-tail policy. Unknown
tiles, duplicate CLI nodes, unsupported override targets, forged choices and
conflicting explicit saved-plan requests are rejected before emission.

The implementation table is the source of truth for supported tile identities.
The same selection drives prepared-bias placement, generated calls, execution
work and viewer metadata. Spatial reuse changes the reduction schedule, so its
execution work is labelled `dense_pointwise_scalar_dot8_spatial2`. Useful product
counts and graph MACs do not change. The previous one-pixel kernels and scaling
policies remain independently selectable for comparison. The unselected control
build must retain identical allocated sections and loadable bytes to its parent.

The accepted software configuration uses **2x2 tiles for all 32 pointwise
layers**, preserving the parent's per-node scaling choices. It retires
**1,576,585,275 instructions (4.451% fewer)** and **479,017,527 memory instructions
(14.386% fewer)**. Code shrinks from 54,520 to 52,468 bytes; the observed
canonical-input stack watermark remains 584 bytes. The 2x4 experiments regress
with substantial SP-relative traffic under the pinned GCC build and are retained
as measured alternatives. `compiler-b1-spatial-checkpoint` selects the accepted
2x2 experiment; the four explicit tile/scaling experiment targets remain
available. [Comparison and acceptance evidence](../results/profiling/B1-spatial-comparison/README.md).
