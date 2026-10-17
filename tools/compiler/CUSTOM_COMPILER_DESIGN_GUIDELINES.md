# Model-Specific TFLite-to-C++ Compiler — Design Guidelines and Staged Implementation Plan

**Project:** EfficientNet-Lite0 quantized inference on bare-metal RV64IMC / CV-Wally  
**Purpose:** Implement an understandable, reproducible AOT compiler that generates efficient C++ for B1 and custom-ISA code for X1/X2, while keeping the existing LiteRT Micro baseline (B0) unchanged.  
**Status:** Implementation specification, not a claim that any compiler stages already exist.  
**Working principle:** Correctness first; one independently verifiable stage at a time.

---

## 1. Source of truth and project constraints

Before coding, read these **tracked repository files** (paths relative to the existing repository root):

1. `instructions.md` and `clarifications.md` — assignment requirements and permitted runtime strategies.
2. `README.md`, `models/README.md`, and `models/efficientnet-lite0-int8.audit.json` — selected model and constraints.
3. `tflm/README.md`, `tflm/efficientnet_lite0.cc`, and `tflm/platform/rv64imc/README.md` — reference execution and bare-metal platform.
4. `docs/profiling.md`, `results/profiling/B0/README.md`, `results/profiling/B0/analysis.md`, and `tools/profile_spike.py` — baseline methodology and profiler interface.
5. `Makefile`, `tools/inspect_tflite.py`, and `tools/audit_rv64_elf.py` — existing build, frontend inspection, and ISA auditing.

**Verified starting facts (from the supplied repository):**

| Property | Current baseline |
|---|---|
| Model | `models/efficientnet-lite0-int8.tflite` |
| Model SHA-256 | `31c18ecf5cfb7bddf182e450e4029834271fc70e15b5fae6ddb5995ac2a6de51` |
| Graph | 1 static subgraph; 64 operators; 166 tensors |
| Operators | 33 Conv2D, 16 DepthwiseConv2D, 9 Add, 2 Quantize, 1 AveragePool2D, 1 FullyConnected, 1 Reshape, 1 Softmax |
| Versions | Conv/Depthwise v3; Add/Pool/Softmax v2; FC v4; Quantize/Reshape v1 |
| Arithmetic | INT8 inner activations/weights, INT32 biases; UINT8 public input/output; per-channel convolution/depthwise weights |
| Public input and output | `[1,224,224,3]` UINT8 and `[1,1000]` UINT8 |
| TFLM revision | `9f638f18154dff868e7053572f089be845b2fbdf` |
| Spike revision | `19609434bb3d83448eec8796e8f0367c868efbda` |
| GCC | Pinned xPack RISC-V GCC 15.2 release in `Makefile` |
| ISA/ABI | `-march=rv64imc -mabi=lp64`; no FP/vector/atomic hardware |
| B0 full inference | **4,867,278,370** retired instructions |
| B0 operator dispatch overhead | **4,820** retired instructions |
| B0 reference memory | Static 2 MiB arena; **1,688,176** bytes used |
| B0 deterministic output | `output_top_index=21`, `output_top_score=48`, `output_sum=215`, `output_fnv1a=0x4b6a91e2` |

The B0 output corresponds to **one deterministic synthetic input**, not an image-accuracy benchmark. Capture multiple additional inputs and intermediate tensors before claiming broad correctness. The 128 MiB Spike linker RAM mapping is **not** proof that any specific CV-Wally implementation has that much physical RAM.

**Assignment obligations to preserve:**

- B0: original LiteRT Micro on RV64IMC.
- B1: optimized **software only**, still RV64IMC.
- X1: incremental use of the packed INT8 MAC instruction (`Xqmac`, potentially the chosen `Xqmac8` design).
- X2: additional ISA configuration. **Resolve the assignment wording explicitly:** §3 calls packed MAC **and requantization** the minimum extensions, while §4 says X2 is optional. Plan for requantization; do not silently drop it.
- Measure dynamic instructions, instruction mix, memory instructions/MAC, MAC/instruction, operator contribution, code size, and custom-instruction frequency. Provide microbenchmark, at least two major operators, and full inference or a complete block.
- Later evaluate at least one kernel in CV-Wally RTL, with cycles, CPI, speedup, clock frequency/critical path, and area/resource impact. **Spike retirements are not hardware cycles.**
- The assignment allows offline conversion of graph information and parameters into static C data structures. The clarification identifies LiteRT-based bare-metal execution as the emphasis. Therefore, **keep the pinned LiteRT Micro B0 running and document the AOT generated backend as a controlled comparison to it**, rather than replacing or deleting B0.

---

## 2. Compiler mission and non-goals

### Mission

Generate a **fixed-model, bare-metal, deterministic C++ implementation** of the exact TFLite graph, with:

- Readable code and inspectable stages: `TFLite → graph IR → prepared parameters → kernel plans → memory plan → C++ → ELF`.
- Validated integer quantization semantics against pinned TFLM.
- Direct operator execution without a dynamic interpreter; reused and/or generated C++ kernels.
- One set of model semantics and memory plans for the A0, B1, and X1 backends whenever feasible.
- Source/provenance maps for the existing CNN-to-assembly web explorer and Spike attribution.
- Native-host correctness tests first; RV64IMC and Spike tests after.

### Explicit non-goals for the first implementation

- Arbitrary TFLite models, dynamic shapes, control flow, training, FP graph operators, generic tensor broadcasting beyond this model, or arbitrary TFLite custom ops.
- A general optimizer such as MLIR/TVM, a custom assembler or register allocator, automated instruction scheduling, or generating machine code directly.
- Graph fusion, full-model loop unrolling, complex tiling/DMA, hardware cycle simulation, or automatically choosing the optimal code shape.
- Rewriting fixed-point softmax/requantization before a reference-equivalent model executes.
- Removing B0, changing its original model, loosening correctness tests, or labeling optimized code B0.

**Design preference:** Python 3.12 for offline frontend/passes, a small typed graph and kernel-plan IR, generated C++17 and reusable kernel templates, and existing GCC for machine-code optimization. Borrow ideas from TVM (explicit IR/pass separation), TinyEngine (AOT kernels/memory planning), and TFLM (quantized numerical contracts), but **do not add those compiler frameworks as mandatory dependencies**.

---

## 3. Proposed package boundaries

Add a separate tracked implementation; do not modify downloaded `.deps/` sources in place.

```text
compiler/
  __init__.py
  cli.py                 # import / validate / generate / inspect
  frontend.py            # TFLite FlatBuffer import; no code generation
  ir.py                  # typed graph, tensors, operators, quantization
  validation.py          # model contract + shape/options checks
  quantization.py        # exact prepared-parameter computation/validation
  kernel_plan.py         # implementations, blocking, scratch contracts
  memory_plan.py         # tensor lifetimes, aliases, alignment, scratch
  lowering.py            # IR -> selected kernel and runtime plans
  emit_cpp.py            # deterministic readable C++ generation
  manifest.py            # versions, hashes, provenance
  templates/             # minimal templates, not giant string builders
kernels/
  reference/             # reference-compatible wrappers / borrowed pinned helpers
  rv64imc/               # portable scalar specialization (B1)
  xqmac/                 # custom-ISA wrappers and adapters (X1)
tests/compiler/
  fixtures/              # small synthetic graphs and integer test cases
  test_frontend.py
  test_quantization.py
  test_memory_plan.py
  test_codegen.py
  test_differential.py
tools/
  capture_tflm_oracle.py # optional helper for reference prepared data/tensor outputs
build/compiler/           # ignored generated models, binaries, dumps, logs
```

The exact filenames may evolve, but **separation of responsibilities must not**. `build/compiler/` and machine-generated C++ are ignored outputs; code generators, templates, tests, and reproducibility scripts are tracked.

### Data contracts

**Graph IR** records at minimum:

- Original subgraph, tensor, and operator indices; graph inputs/outputs; producer/consumer edges in the actual graph.
- Tensor name, shape, shape signature, type, storage class (constant/runtime/alias), buffer ID, byte length, layout, and quantization (scales, zero-points, quantized dimension).
- Operator code, version, complete builtin options (padding, stride, dilation, depth multiplier, fused activation, `keep_dims`, etc., as applicable), named inputs/outputs, and validated shape inference.
- The exact reference integer arithmetic contract and optional/absent operands, not just floating-point-scale descriptions.

**Kernel plan** records per node:

- Selected implementation and fallback, supported shapes/type constraints, blocking and unrolling choices, weight layout, in-place behavior, required alignment, scratch size/lifetime, and arithmetic backend.
- Mapping to original node ID, generated symbol, source region, and optimized/reused constants.

**Memory plan** records per tensor/scratch buffer:

- Size, alignment, start/end lifetime, storage class, arena offset, alias/in-place eligibility, and required memory capacity.

**Manifest** records:

- Input-model SHA-256, generator source revision/dirty state, TFLM and toolchain revisions, `-march/-mabi`, resolved compiler/linker flags, backend and optimization options, pass list, graph/kernel/memory-plan hashes, generated source hashes, and ultimately ELF hashes and validation outputs.
- Stable schema version and explicit evidence/capability fields. No embedding of volatile timestamps into deterministic generated source files.

Reject unsupported IR/configuration combinations **before** generating code. No quiet fallback to floating-point arithmetic, guessed quantization values, or silently ignored operator options.

---

## 4. Engineering rules for every implementation stage

1. **One stage per agent task.** Read its prerequisites and complete only its deliverables. Do not start the next stage without recording a passing gate and obtaining the next instruction.
2. **Preserve B0.** No edits to the tracked baseline behavior or pinned upstream revisions unless explicitly authorized. Avoid source changes under `.deps/`; use tracked wrappers, patches, or generated artifacts.
3. **Use incremental changes.** Prefer small reviewed modules, deterministic inputs, unit tests, and clear failure errors to a monolithic generator.
4. **Prove rather than assume.** Document which facts come from the actual model, which from the pinned TFLM reference, which from source/disassembly, and which are hypothetical optimizations.
5. **Bit-exactness is the default.** Match the reference output tensor byte-for-byte across multiple inputs; inspect the **first divergent node** when tests fail. Report numerical approximations separately if ever considered.
6. **Avoid C++ undefined behavior.** Check int32 overflow or define wrapping semantics appropriately; do not dereference misaligned/alias-unsafe `uint64_t*` casts; use explicitly defined packed loads and lane ordering.
7. **Do not overoptimize the baseline.** A0 proves AOT correctness; B1 measures software optimization; X1/X2 measure incremental ISA improvements. Keep the causal attribution clear.
8. **No claims from missing measurements.** If Spike captures, TFLM source, a RISC-V toolchain, or CV-Wally hardware are unavailable, implement/test what is possible and mark missing gates as **blocked**, not passed.
9. **Keep generated execution observable.** Emit stable node IDs/symbols, optional region instrumentation, source maps, and a report-compatible manifest.
10. **No runtime heap allocation.** Inference uses static/predetermined buffers and read-only constant arrays; setup decisions occur offline. Small stack locals are acceptable; audit their peak usage.

### Required agent handoff after every stage

Report all of the following in the final stage response or `build/compiler/stage-N-report.md`:

- Implemented scope and important design decisions.
- Exact files created/modified and CLI/build commands to reproduce.
- Tests executed with **actual pass/fail results**, counts, representative fixtures, and hashes when relevant.
- Any unresolved ambiguity, limitation, known unsupported feature, or regression.
- Gate checklist, labeled **PASS / FAIL / BLOCKED**.
- Next stage prerequisites only; do **not** quietly advance scope.

---

## 5. Staged implementation roadmap

| Stage | Deliverable | Must pass before advancing |
|---|---|---|
| **0** | Frozen baseline + compiler test harness | Reproduce/verify B0 from current environment; reference fixtures recorded |
| **1** | TFLite parser + strict graph IR | Parse/validate exact 64-node model and reject unsupported fixtures |
| **2** | Quantization oracle + exact operator contracts | Prepared-parameter parity with pinned TFLM; targeted integer tests |
| **3** | Static tensor/scratch memory planner | No conflicting live buffers; alignment and alias checks |
| **4** | Standalone, correct A0 C++ model | Whole-model and node-wise equality vs. TFLM on several inputs |
| **5** | B1 scalar 1×1 convolution optimizations | Bit-exact; RV64IMC only; measured B1 vs A0/B0 |
| **6** | B1 depthwise / other hotspot tuning | Each extra optimization has independent measurements and rollback |
| **7** | X1 packed MAC backend + Spike integration | Directed/random ISA tests, exact CNN outputs, per-node utilization/counts |
| **8** | Requantization instruction backend (X2 or required additional ISA configuration) | Bit-exact scaling, incremental vs X1 metrics |
| **9** | Final compiler validation, artifacts, profiling/explorer handoff | Reproducible builds and complete configuration comparison |

The later **CV-Wally RTL/area/cycle evaluation is a separate hardware workstream** using the kernels and test vectors produced in stages 7–9. The compiler must not substitute Spike counts for RTL cycle results.

### Stage 0 — Freeze B0, infrastructure, and golden tests

**Goal:** Obtain a clean, immutable reference and reliable tests before changing inference execution.

**Implement:**

- Confirm/check in the current model hash, model audit, TFLM/Spike revisions, toolchain and build commands.
- Preserve the reference executable, B0 `summary.json`/`layers.csv`, verified output checksum, and (if available) the original raw PC captures and debug ELF, under ignored artifact paths or documented immutable archive locations.
- Add a minimal compiler CLI skeleton (`validate`, `generate`, `inspect` commands can initially report not implemented), native build/test harness, and deterministic test-input generator matching the existing application's byte sequence.
- Define a **reference-output capture path**: native TFLM run that records complete intermediate output tensors (or hashes plus retrievable full arrays) for each of 64 operators for multiple deterministic, edge-case, and randomized inputs. Avoid changing baseline performance instrumentation: instrument a separate oracle build.
- Specify the measured boundary for generated inference and how it aligns with `MicroInterpreter::Invoke()`'s B0 region; exclude input generation, setup, checking, and printing.

**Tests/gate:**

- Existing commands when the environment supports them: `gmake run-native`, `gmake run-spike`, `gmake profile-tests`, and, where raw captures can be regenerated, `gmake profile-spike` / `gmake profile-report`.
- Capture the deterministic 1,000-byte output reference including checksum `0x4b6a91e2`; obtain representative per-node reference tensors for future differential tests.
- Verify B0 remains unchanged in Git and that compiler directory creation doesn't change its measured program.
- **Stop** before generating real convolution implementations.

### Stage 1 — Complete importer and strict graph IR

**Goal:** Convert the TFLite FlatBuffer into an inspectable validated model description; **no C++ inference generation yet**.

**Implement:**

- Build upon `tools/inspect_tflite.py` (reuse helpers where appropriate), using pinned or version-controlled `tflite` FlatBuffer Python bindings.
- Parse actual tensor buffer contents with type, length, byte order, shape, original tensor IDs and named graph dependencies.
- Decode and validate every builtin option and operator version for all eight supported kinds. Validate padding conventions, stride/dilation, depth multiplier, fused activations, quantized axes and scales, optional inputs and output shapes.
- Validate single static subgraph, unsupported custom ops/control flow, malformed or multiple producers, bad buffer sizes, inappropriate zero-points/types, invalid tensor indexes, and shape inconsistencies with helpful errors.
- Export canonical `graph_ir.json`, human-readable per-node table, and DOT/edge graph optional for the explorer. Maintain stable original node/tensor identities.

**Tests/gate:**

- Read the tracked model hash; import **64 ops / 166 tensors / 1 subgraph**; match recorded audit counts and operator versions.
- Verify graph tensor edges including all nine residual ADD nodes; verify actual tensor shapes/types/quantization and constant byte lengths.
- Unit tests intentionally reject unsupported versions, invalid shapes, bad quantization axis, missing buffers, and malformed edges.
- Round-trip/serialize the normalized IR deterministically and assert stable hashes on identical input.
- **Stop** before code generation, optimization, or memory allocation.

### Stage 2 — Numerical contracts and prepared-parameter reference oracle

**Goal:** Establish exact integer semantics for every operator before generating an independent runtime.

**Implement:**

- Extract/compare TFLM-prepared parameters for Conv, Depthwise, FC, ADD, quantization boundary conversions, Pool, and Softmax, using the **pinned** reference sources and preparatory callbacks where needed.
- Represent prepared per-channel/per-tensor multipliers, shifts, zero-points, clamp bounds, padding, effective bias scales, and operator-specific fixed-point constants explicitly in IR.
- Decide and document the exact reference rounding mode, arithmetic shifts, activation/saturation behavior, signed range and accumulator overflow assumptions; identify compile-time vs runtime-dependent parameters.
- Validate symmetric INT8 weights but **preserve asymmetric activation zero-points**. For unpadded 1×1 Conv, prove/test the adjusted-bias transformation: `b'[oc] = b[oc] + input_offset * sum(weights[oc,:])`, using wide preparation intermediates and checks for narrowing.
- At padded boundaries, **do not** use one all-filter constant correction unless the generated kernel processes padded locations as quantized zero or otherwise accounts for valid taps. Build targeted border cases.
- Where exact TFLM helper reuse is best (e.g. fixed-point requantization/Softmax), provide a standalone-callable wrapper rather than rewriting the arithmetic prematurely.

**Tests/gate:**

- Prepared integer parameters agree with pinned TFLM **element by element**, not approximately.
- Directed tests for `-128`, `127`, zero-points, output clamp extremes, positive/negative rounding boundaries, long accumulations, absent bias, residual ADD with differing input scales, and padded convolution borders.
- Independent scalar dot-product tests and adjusted-bias tests preserve exact results where transformation is enabled.
- All implemented numeric paths compile in the native-host tests without implementation-defined or undefined signed-overflow assumptions.
- **Stop** before a full generated inference executable.

### Stage 3 — Static memory planning

**Goal:** Compute addresses for all runtime tensors and scratch before execution; no allocator at inference time.

**Implement:**

- Derive producer, earliest use, and **last consumer** for each runtime tensor, including skip-connection lifetime extensions and externally visible inputs/outputs.
- Separate immutable weights/params (`.rodata`), activation workspace (`.bss`), operator scratch, and ordinary stack locals.
- Introduce a *kernel memory contract*: scratch requirements, operand alignments, and whether read/write or output/input aliasing is explicitly safe.
- Implement a deterministic aligned greedy/first-fit allocator (not necessarily identical to TFLM's). Treat simultaneously live input and output tensors as conflicting unless the selected kernel formally supports in-place execution.
- Permit `RESHAPE` views only when representation and later writes are proven safe; otherwise allocate/copy. Treat conditional scratch buffer lifetimes accurately.
- Export `memory_plan.json`, peak bytes, per-tensor lifetime chart data, collision checks, and budget warnings. Parameterize memory limits for Spike and eventually CV-Wally rather than assuming the 128 MiB linker map is on-chip RAM.

**Tests/gate:**

- On adversarial synthetic graphs, assert overlapping live intervals never overlap in storage (unless proven safe alias), and all offsets satisfy alignment and bounds.
- Exercise residual lifetimes, scratch sharing, absent/zero-sized tensors, reshape alias decisions, large 1.2 MB tensors, and failed memory-budget cases.
- Generate a plan for the real model; compare its activation/scratch use with TFLM's 1,688,176-byte **total arena usage**, explicitly noting that persistent TFLM metadata makes this an apples-to-oranges size comparison.
- **Stop** before optimizing kernel algorithms.

### Stage 4 — A0: reference-equivalent standalone C++ execution

**Goal:** Produce an executable **without the TFLM interpreter** while retaining reference numerical behavior. A0 is an **internal diagnostic** configuration, not a replacement for the required B0 label.

**Implement:**

- Emit deterministic, readable C++17 containing fixed graph execution order; constant weights/params; a statically planned activation arena; and calls to reference-compatible operator implementations.
- Prefer linking or using selected pinned TFLM **reference integer arithmetic helpers/kernels** where legally/technically appropriate; avoid reproducing all quantized operators from memory. Exclude the interpreter itself.
- Provide native host and bare-metal RV64IMC builds using existing platform startup/HTIF support, or minimally duplicated tracked platform glue. **Do not** assume normal hosted `main()` and libc facilities on bare metal.
- Preserve **UINT8 public input/output and both QUANTIZE boundary conversions**, the complete 64-node graph, and the same deterministic input-generation/checksum convention as B0.
- Embed stable per-node instrumentation hooks or non-inlined measurement wrappers that do not modify computational results, and emit `source_map.json`: original node ID → generated function/symbol → source location.
- Emit comparison test hooks to access each intermediate tensor. Limit debugging instrumentation to a dedicated build if it perturbs inference metrics.

**Tests/gate:**

- Native A0 agrees byte-for-byte with pinned TFLM for **every node's complete output tensors**, tested on several deterministic and randomized external UINT8 inputs. When checking physical reused buffers, snapshot a node's output **when produced**, before overwrite.
- RISC-V A0 compiles for `rv64imc/lp64`, passes ELF audit, runs in unmodified Spike with the correct 1,000-byte output and checksum; no actual FP/vector/atomic hardware instructions.
- Memory guard tests, host address/UB sanitizers, and runtime bounds checks pass where available.
- Profiling boundaries are semantically comparable: same model computation, no setup/output verification inside inference; explicitly label remaining instrumentation overhead.
- **Do not call A0 B1** or claim a performance win merely because interpreter dispatch disappeared.

### Stage 5 — B1: software-only specialized 1×1 convolutions

**Goal:** Introduce isolated **RV64IMC-only** software optimizations with trustworthy measurements.

**Implement:**

- Introduce a `KernelPlan` that chooses optimized 1×1 paths for proven supported combinations; conservative reference fallback for everything else.
- Use precomputed corrected biases where safe; pointer-based NHWC/OHWI addressing, short fixed reductions, channel/output-channel tiling, activation reuse, and selectively unrolled loops.
- **Check compiled disassembly** before claiming that a C++ rewrite eliminated indexing. GCC already reduces some B0 `Offset(...)` accesses to pointer increments.
- Maintain a scalar `dot8` abstraction matching X1's eventual eight-lane input grouping, but expressed using ordinary ISA operations. Reuse blocking/layout/accumulator flow when feasible between B1 and X1.
- Parameterize unrolling/tiling and record static code size; do not explode the binary with one fully unrolled function per output location.

**Tests/gate:**

- Start with **node 4** (`[1,112,112,16] × [96,1,1,16] → [1,112,112,96]`) and **node 58** (reduction depth 320). Compare *complete output tensors*, not merely MAC sums.
- Make one software change at a time; differential tests pass against A0 and B0 for multiple inputs.
- Build an audited **RV64IMC-only** B1 ELF; no custom opcodes.
- Record node-level and full-model retired instructions, instruction mix, load/store per product, code size, checksum and reproducible compiler flags. Report the benefit vs both B0 and A0.
- Reject/roll back nonbeneficial changes unless retained explicitly for a proven later X1 integration reason.

### Stage 6 — B1: depthwise and remaining measured hotspot improvements

**Goal:** Improve generic depthwise instruction overhead without contaminating X1 attribution.

**Implement:**

- Specialize 3×3/5×5 depthwise kernels, hoist constant strides/indexing, use pointer increments, split interior/border computations where worthwhile, and avoid unneeded branching.
- Prioritize **node 8** (3×3) and **node 15** (5×5); preserve depth multiplier, padding, fusion and per-channel fixed-point scaling contracts.
- Keep an explicit fallback and independent feature flags for each optimization so results can be attributed separately.
- Only optimize FC/ADD/Softmax further if measurements warrant it. Avoid assuming `Xqmac8` maps naturally to depthwise channels with **independent accumulators**.

**Tests/gate:**

- Node-level output equality including border pixels; full graph still exact.
- Show measured reduction of indexing/address/control instructions for affected nodes, or record why the change was rejected.
- B1 remains RV64IMC-only and demonstrably distinct from B0.

### Stage 7 — X1: `Xqmac8` backend and simulator integration

**Goal:** Replace groups of eight scalar products with the custom ISA instruction while preserving B1's algorithm and graph behavior.

**Prerequisite:** The **ISA contract is signed off** with the hardware implementation owner before compiler backend work. Document `rd/rs1/rs2` meaning, possible old-`rd` third read, encoding, signed 8-bit lanes, lane order, accumulator width and overflow, 64-bit writeback, hazards/latency assumptions, alignment, and fallbacks.

**Implement:**

- Add tracked Spike extension patch/instructions, correct decoder/disassembler/profiler classification, directed and randomized instruction tests.
- Add `xqmac8(acc, packed_a, packed_w)` using a compiler-visible intrinsic or carefully constrained inline `.insn` assembly; **avoid assuming GCC automatically recognizes a C++ dot product as a custom instruction**.
- Use safe portable packed loads (e.g., fixed-size `memcpy` with verified target codegen), explicit little-endian lane convention, and fallback for channel tails or unsupported shapes.
- Reuse B1 weight layout, blocking, bias correction, quantization and memory plan as closely as possible. One code-generation option chooses scalar dot8 vs custom dot8.
- Measure actual emitted assembly, not estimated instruction counts. Ensure `PROFILE_CONFIGURATION=X1` selects a **different real binary/backend**; the current Makefile flag alone merely changes profile labels.

**Tests/gate:**

- Directed tests: signed extremes, lane permutations, negative products, repeated accumulator updates, overflow behavior, and RV64 sign extension. Random tests match an independent bit-exact oracle.
- X1 full-model and representative node output tensors match B1/A0/B0 on multiple inputs.
- Spike correctly decodes, executes, and counts actual custom opcodes; no unintended custom instructions in B0/B1.
- Record incremental **B1 → X1** instruction benefit, per-node custom frequency, load/store per product, code footprint, and total inference change.
- Provide a hardware-facing ISA vector suite for CV-Wally without claiming RTL cycle results yet.

### Stage 8 — Requantization extension and incremental X2 evaluation

**Goal:** Implement the required fixed-point scaling extension in isolation from the MAC benefit.

**Implement:**

- Resolve the naming ambiguity with assignment §3/§4 in documentation. Treat the requant instruction as planned scope even if X2 is described as optional.
- Specify all rounding, shift, saturation, zero-point, negative accumulator and overflow details, including which operands are embedded constants vs registers and how multi-parameter encoding works.
- Implement verified Spike semantics and a small wrapper; add backend selection that changes only the requantization lowering where possible.
- Audit both convolution/depthwise and the quantized ADD path: the B0 out-of-line `MultiplyByQuantizedMultiplier` count is **not** the complete scaling cost.

**Tests/gate:**

- Boundary/fuzz tests match pinned TFLM exactly across all observed multipliers and shifts.
- The full model remains bit-exact.
- Report **X1 → X2** incremental instruction counts, custom utilization, code size and eventually RTL cycles separately from B0 → X2 combined improvement.
- Never label hypothetical cycle savings as measured speedup.

### Stage 9 — Harden, package, and integrate with the explorer/report

**Goal:** Make the compiler reproducible and usable for the final project comparison.

**Implement:**

- One documented command each for `import/validate`, `generate --config A0|B1|X1|X2`, `build`, `run-native`, `run-spike`, `profile`, and `report`. Add `gmake` wrapper targets **without changing the meaning of existing B0 targets**.
- Deterministic generated source, constant arrays, `graph_ir.json`, `kernel_plan.json`, `memory_plan.json`, `source_map.json`, and `manifest.json` with verified hashes.
- Produce equivalent operator-region events for the generated path so the current profiler can attribute node-local PC counts. Do not assume the existing TFLM callback recognizer directly handles standalone code; explicitly extend/test the collector or measured wrappers.
- Connect generated node/source/ELF mappings to the web explorer through a versioned portable bundle if the explorer project is available. Do not make the explorer a requirement for running the compiler.
- Generate compact report tables across B0/A0/B1/X1/X2, including all required assignment ISA metrics, correctness, and missing hardware metrics clearly marked not yet measured.
- Write a hardware handoff: ISA encoding and semantics, directed vectors, chosen kernels, workload traces/counters, relevant critical paths to test, and memory map assumptions.

**Tests/gate:**

- Fresh-checkout reproducible host and RV64 builds in a supported environment; fully documented pinned dependencies.
- Exact output checks (all intermediate tensors on multi-input differential tests), clean ISA audits, profile capture repeat agreement and instruction-total reconciliation.
- File-hash matching between model, sources, compiler artifacts, ELF and profiler report.
- The standard project commands still run B0 identically.
- A reviewer can identify every model node's generated function, code, data, memory allocation, execution counts and arithmetic backend.

---

## 6. Measurement and correctness policies

### Results must distinguish these comparisons

| Comparison | Valid interpretation |
|---|---|
| **B0 → A0** | Interpreter/preparation/runtime restructuring, **not** custom-ISA gain |
| **A0 → B1** | Generated **software** kernel optimization under RV64IMC |
| **B1 → X1** | Incremental packed-MAC ISA impact with algorithms held comparable |
| **X1 → X2** | Incremental requantization ISA impact |
| **B0 → B1/X1/X2** | Combined end-to-end benefit relative to assignment baseline |

### Accuracy and semantics

- Keep the exact model and external UINT8 input/output interpretation. Do not silently strip the two `QUANTIZE` boundary ops.
- Test whole tensors immediately after each node; include representative synthetic, edge and randomized inputs, and an image-based accuracy benchmark only if comparable labeled data is available.
- `acc += (q_x + input_offset) * w` and preadjusted-bias dot products are equivalent **only under supported assumptions** about padding, grouping, int32 range, and absence/presence of bias. Validate before substituting.
- Reuse reference-compatible integer quantization helpers until independently verified replacements are available.
- Hashes/checksums are smoke tests; exact array comparisons diagnose failure and provide stronger evidence.

### Profiler discipline

- Keep setup separate from inference, just as the current B0 profiler separates `AllocateTensors()` from `Invoke()`.
- Distinguish **inclusive per-node callbacks** from **exclusive function-body attribution**. Never sum overlapping source/inline-frame counts as disjoint costs.
- The original B0 collector assumes a fixed 64-op TFLM callback order; generated dispatch needs its own validated instrumentation path.
- Counts of dynamic memory instructions are **not** DRAM bytes/cache misses, and Spike's modeled `mcycle` is **not** CV-Wally pipeline timing.
- Include execution contribution, instructions per executed product, MAC/instruction, loads+stores/product, custom-instruction count/frequency, ELF code size, and static memory use. Preserve meaningful static vs dynamic instruction distinctions.

### Known representative cases

| Node | Case | Why |
|---|---|---|
| 4 | 1×1 Conv, K=16 | Hottest representative short dot-product; 327,839,821 B0 instructions |
| 58 | 1×1 Conv, K=320 | Long dot product, blocking/reuse and accumulator tests |
| 8 | 3×3 Depthwise | Indexing/control hot path |
| 15 | 5×5 Depthwise | Different kernel/padding pattern |
| 1 | Stem 3×3 Conv, input depth 3 | Padding/border and non-multiple-of-eight cases |
| 61 | FullyConnected | Independent dot-product correctness/microbenchmark |

---

## 7. Practical agent task template

Give the agent **one stage at a time** using this template:

> Implement **Stage N — [name]** from `CUSTOM_COMPILER_DESIGN_GUIDELINES.md` in the current repository. First inspect the relevant tracked source files and existing tests. Implement only this stage's scope; preserve B0 and all previous passing stages. Prefer reproducible tracked tools to edits inside `.deps/`. Run the required unit, differential, native, Spike, and/or ISA-audit checks that are possible for this stage. Do not claim tests pass without running them. If a prerequisite is unavailable, mark that gate BLOCKED and explain exactly why rather than substituting an assumption. Finish with changed files, exact commands, output/test evidence, accepted limitations, PASS/FAIL/BLOCKED gate statuses, and an explicit handoff to the next stage. **Stop after Stage N; do not implement Stage N+1.**

For optional subtasks within a stage, use **small PR-sized slices** and keep the stage acceptance gate unchanged. If a stage gate fails, fix it before proceeding or document the blocker explicitly. Do not add speculative architecture extensions or unrelated refactors.

---

## 8. Final compiler acceptance criteria

The compiler implementation can be considered complete for the software/ISA side only when:

- [ ] The exact tracked EfficientNet-Lite0 graph is imported with all operator options and quantization metadata validated.
- [ ] Pinned TFLM-prepared integer parameters and node-wise output tensors are matched across multiple test inputs.
- [ ] A0 runs the complete model without the TFLM interpreter, with known static memory and no unsupported ISA instructions.
- [ ] B1 uses genuinely different optimized RV64IMC kernels and has measured results distinct from B0/A0.
- [ ] X1 contains the verified custom packed MAC, produces exact outputs, and records actual custom-instruction frequency and incremental counts.
- [ ] Requantization extension is addressed per the assignment's minimum requirement, with independently verified exact semantics and incremental measurements.
- [ ] Offline memory planning passes alias, lifetime, alignment, bounds and budget checks.
- [ ] All configurations have reproducible manifests, ELF/ISA audits, code footprint and per-operator profiler attribution.
- [ ] B0 remains runnable and unchanged.
- [ ] CV-Wally kernel cycles/timing/area remain a clearly tracked **separate** hardware gate; no result is inferred from Spike alone.

**Priority order if time becomes constrained:** Preserve B0 → establish A0 numerical parity → deliver measured B1 1×1 optimization → integrate verified X1 → implement required requantization semantics → complete hardware evidence. Depthwise tuning, advanced code generation, and UI polish must not jeopardize required ISA/RTL deliverables.
