# Execution Atlas

Execution Atlas is a local, browser-only evidence explorer for the existing
EfficientNet-Lite0 RV64IMC profiling workflow, including LiteRT B0 and compiler A0. Select an operator, inspect its
hot assembly loops, follow source mappings, and optionally inspect matching
GCC representations. No inference code or Spike instrumentation is changed.

## Compiler builds and memory visibility

```sh
gmake compiler-export
gmake explorer-dev PROFILE_CONFIGURATION=A0
```

Open **Explore A0 build**, or upload `build/explorer/A0.zip` into an existing
viewer. This verifies an immutable compiler capture and its optional byte-identical
GCC archive. It uses frozen source snapshots rather than export-time working-tree
files. The compiler analysis includes all executable C++ translation units (five
for A0); the four-file whitelist below applies only to the LiteRT adapter.
Use `COMPILER_ANALYSIS=` to export without GCC dumps.

**Compilation and memory plan** exposes execution-unit identity, backend, operands,
prepared parameters, compiler choices, source regions and supporting JSON artifacts.
**Generated source** navigates to the compiler-known region; inline DWARF frames
and source-line matches connect it to assembly. The planned-memory chart's horizontal
axis is **execution steps**, with inclusive lifetimes and byte offsets vertically.
Select a storage group to inspect its range; expand tables for every placement,
alias, tensor lifetime and scratch contract. Capacity, peak live activations,
scratch, planned read-only storage and unavailable stack measurements stay separate.

Logical nodes may map to several units, share a fused unit, or be eliminated. The
scope selector provides both units and logical-node views. Shared costs display the
full measurement with a label; split views sum unit events once. Eliminated nodes
show **Unavailable** and the compiler's reason. Summing node cards would double-count
shared units: only unit events plus invocation overhead partition inference.
Allocation is an optional separate setup scope, absent for A0. One imported build
is explored at a time; checkpoint comparisons remain in generated reports.

## Start with this workspace's B0

```sh
npm ci --prefix explorer
gmake explorer-export
gmake explorer-dev
```

Open the printed loopback URL and choose **Explore B0 baseline**. The default
selection is node 4, the highest-cost operator. This workspace has the required
raw captures and measured debug ELF. A repository archive does not contain
those ignored artifacts: reproduce them with the existing profiling workflow
in [profiling.md](profiling.md), or open an exported bundle.

The exporter verifies the model and ELF hashes, disassembly, correctness output,
repeat histograms, callback order, and per-PC/total conservation. Its Python
FlatBuffer/DWARF dependencies are version-pinned in the Make target and run through
`uv`. Existing `profile-report` and `profile-spike` commands are unchanged.

### Add compiler evidence

```sh
gmake explorer-compiler
gmake explorer-export
```

These commands are sequential: export discovers the completed compiler manifest.
The compiler target builds in `build/explorer/compiler/B0/`, records the actual
compiler argument arrays and working directories, resolves dependencies with GCC,
and captures diagnostics for `conv.cc`, `depthwise_conv.cc`, internal `common.cc`,
and `quantize.cc`. It checks the new ELF's loadable sections and segments against
the measured ELF before allowing attachment. Export rechecks the ELF, dependency,
and artifact hashes. A mismatch is a failure, never an approximate attachment.

The compiler tool preserves raw tree/RTL/assembly dumps and indexes functions.
Initial GIMPLE signatures lack linkage names: an unambiguous source function-name
match is used where possible. Ambiguous or unstructured artifacts open as raw
text with a notice. Compiler remarks and pass-discovery output remain searchable.
`-MM` dependencies exclude system headers; the pinned compiler executable/version
and selected build's correspondence to the measured ELF are recorded as well.

Select another saved profile with `PROFILE_CONFIGURATION=B1`. This selects data
and output directories, not another implementation or ISA. Override
`RV64_PROFILE_ELF=/absolute/path/to/its/measured/elf` for that capture. Matching
compiler evidence is attached automatically when its compiler manifest exists;
stale evidence fails validation. To export without it, invoke the Python exporter
without `--compiler-dir`.

## Navigation and interpretation

The three panes are resizable, with a stacked layout on narrow screens. The graph
shows actual tensor edges, including residuals, with costs directly on each node.
Select operators in the graph or through the execution-scope menu.
The execution-scope menu selects an operator, whole inference, setup allocation,
or interpreter overhead. Function counts use exclusive PC attribution; operator
events include callees. Allocation has no invented per-node attribution.

Click an instruction to select its source. Click a mapped source line to select
its hottest associated instruction. All instructions mapping to the selected line at any inline depth
are highlighted in the displayed function, including zero-count instructions.
The assembly heading shows the number of matching instructions. The function menu includes unexecuted
code, and complete disassembly remains visible. Source and assembly support Monaco
Find (Cmd/Ctrl+F). Function/address search, branch targets, basic-block successors,
and selection history provide additional navigation. An unmapped PC shows a source
unavailable state; it never disappears from assembly.

The source heatmap sums instruction retirements attributed to a source line,
not the number of times a C++ statement ran. Each instruction contributes once at
the selected inline depth. The inline-frame selector exposes caller mappings
without adding overlapping frames together. Legacy capture source snapshots are
explicitly **export-time snapshots**: the original capture did not hash source
text. They should not be represented as capture-time textual provenance.

### Register correspondence

The C++ pane also supports click/Enter inspection of variable identifiers.
For the reviewed int8 convolution and depthwise kernels, the popup distinguishes:

- **Model-derived value:** selected-layer batch count, tensor shapes/dimensions,
  convolution groups, strides, dilations, depth multiplier, leading padding, and
  input/output quantization offsets where their evidence is available.
- **Loop variable:** its role and declared bounds for the selected layer, without
  asserting a current iteration or a dynamic trip count.
- **Changes during execution:** accumulators, selected tensor elements, coordinates,
  and padding predicates, whose runtime values are absent from the capture.

Bindings require matching reviewed source hashes, the int8 overload, a compatible
operator and consistent recorded tensor shapes. Parameter-construction and padding
helpers also need matching hashes before their derived values are shown. Values
are calculated from model metadata, not measured register or memory state. Other
files/overloads, stale bindings, scaling arrays and unrecorded values show an
unavailable state. Whole-inference and allocation scopes require selecting a single
operator before displaying layer values. Comments and string literals do not open
variable inspectors. Normal source-line clicks still highlight matching assembly.

Assembly and source lines have no hover panels. Click a register to inspect its
source correspondence, or click an instruction mnemonic (including its `c.`
prefix) for an instruction explanation. With the caret on either token, Enter
opens the same popover. Only one inspector opens at a time; Escape, an outside
click, or scrolling the editor dismisses it.

Instruction help is a locally bundled RV64 reference covering all mnemonics in
the B0 disassembly. It shows the selected operands, a plain-language explanation,
an operation, and the uncompressed equivalent for C-extension instructions.
For example, `c.sdsp x23,216(x2)` writes eight bytes at `sp + 216`, while its
instruction encoding occupies only two bytes. Displayed offsets are already byte
offsets. The popover links to the relevant official RISC-V ISA specification;
opening that external reference is optional. Unknown instructions receive an
explicit unavailable state. Instruction semantics do not assert runtime values
or a compiler's intent.

Assembly branch and call targets keep their numeric address and use concise
demangled labels, for example `bne x27,x14,0x80005c94 # ConvPerChannel + 0x1aa`.
Offsets are bytes from the function entry. Unknown symbols retain the address
without guessed names. Noisy objdump comments are omitted from the main listing.
Click the mnemonic and expand **Original disassembly** to inspect the complete
unmodified operands and symbol annotation. This formatting does not change bundle
data, instruction counts, source mappings, CFG analysis, or register inspection.
Known branch/jump/call target addresses are underlined links. Click one (or press
Enter with the caret on it) to select and reveal its destination instruction,
switching functions and source locations when needed. The target address in the
instruction popup is clickable too. Selection history remembers the originating
branch or call, including when reached by scrolling, so Back returns there.
Addresses absent from the bundle remain plain text.

Click a register token such as `x10` in the assembly view, or place the editor
caret on it and press Enter. A small popover shows the C++ variable name, type,
function, and declaration link when the matching debug information is available.
Click outside or press Escape to dismiss it. This adds no persistent workspace panel.

Mappings are specific to the selected instruction address and describe state
**before that instruction executes**. A destination register may not yet hold the
value that instruction is about to produce. Registers are reused across address
ranges; they do not have one permanent variable name.

The exporter reads DWARF location lists, intersects them with function, lexical,
and inline scopes, and resolves abstract origins for optimized variables. It
supports direct register values, simple register-based memory addresses, and
register pieces, keeping those roles distinct. A bounded subset of byte/word
dereferences is retained as symbolic relationships such as
`filter_val = signed_byte_at(x14 - 1)`; memory is never evaluated. Frame evaluation,
entry-register history, and unsupported expressions remain unavailable.
When direct metadata is absent, the viewer can trace register copies, constants,
addition, subtraction, multiplication, and immediate additions through the static
function CFG. These results carry an **Inferred expression** label and expandable
instruction evidence with their DWARF seed addresses. Every incoming static path
must agree; unchanged loop backedges are supported. Conflicting paths, recursive
value-changing loops, incomplete CFGs, unsupported instructions, untracked loads,
and caller-saved registers across calls remain unavailable. Tracing is bounded;
it does not choose paths using PC counts or evaluate memory. Addresses and partial
variables are never used as named value seeds. Word-operation expressions are
labeled with their 32-bit truncation and sign-extension semantics. Numeric runtime
register values are not present in PC histograms and are not displayed.

In the current B0 loop, `x10` at `0x80005ca8` maps to `acc`, and `x23` at
`0x80005c9e` maps to `input_val`. There is no supported DWARF variable location
for `x8` at `0x80005c9e`, but the copy from `x16` at `0x80005b78` allows the viewer
to infer `input_offset`. After `addw x23,x23,x8`, inspecting `x23` at
`0x80005ca2` (assembly line 158) shows `input_val + input_offset`. This is static
dataflow evidence, distinct from the compiler-recorded `input_val` at line 157.
Names in inferred expressions refer to their values at the listed debug seed
addresses, rather than asserting that those source variables remain unchanged.

For compiler-generated pointers, the popover also shows inferred loop roles,
stride, comparison registers, source declarations, and clickable instruction
evidence. This analysis currently covers complete, single-block natural loops
with positive pointer increments and a `bne` backedge. A loop-end span is shown
only when bounded static add/copy analysis proves the difference from the initial
pointer on every incoming path. Model-derived byte spans require a matching,
reviewed source declaration for a scalar dimension load. They describe the
selected operator, not a sampled register value.

At `0x80005cac`, B0 identifies `x14` as the advancing filter pointer and `x27` as
its end pointer: `x27 = initial(x14) + filter_input_depth`. Node 4 has a
model-derived span of 16 bytes. The nearby `filter_val` DWARF relationship ends
at this branch's address, so it is explicitly labeled as nearby evidence rather
than an active variable mapping. Supporting evidence links to the applicable
address ranges and source. Verified compiler artifacts additionally identify
`x14` as `ivtmp.85` and `x27` as `_90`, and open the matching final RTL section.
These links require a unique loop sequence and backedge match across final RTL,
emitted assembly, and measured disassembly; ambiguous or relaxed sequences are
left unlinked. Numeric RTL instruction IDs are not treated as machine addresses.

Register metadata is optional in bundle version 2. Version 1 imports are rejected;
use `gmake explorer-export` to regenerate historical B0 evidence in v2.
This enrichment uses the existing measured ELF, histograms, and verified compiler
artifacts; it does not require another full Spike inference run.
The exporter uses pinned `pyelftools==0.32` in addition to the model bindings.

### Assembly Analysis

Open **Assembly Analysis** beneath the workspace for hot loops, instruction mix,
tensor metadata, and basic-block navigation. It starts collapsed, independently
of the GCC Advanced Analysis panel, so the main assembly pane stays focused on code.

### Hot loops

Basic blocks and edges are derived from decoded instructions. Dominators identify
natural-loop back edges; latches sharing a header are merged and nested loops
are retained. Strongly connected cyclic regions without a dominating header are
shown separately as irreducible cycles. Indirect transfers and missing successors
mark incomplete control flow. Static call continuations assume the call returns;
no dynamic call order or edge frequency is inferred.

A loop's inclusive body count sums the selected event's counts for its static
instruction set. Its exclusive count removes the union of immediate child-region
instruction sets. Nested inclusive totals overlap and must not be added together.
The counts exclude out-of-line callee bodies; loop-specific callee work, trip
counts, and branch-taken frequencies cannot be recovered from these histograms.

For B0, choose whole inference and the eight-instruction loop at `0x80005c94`:
its static body accounts for 2,794,488,576 retirements, or 57.41% of inference.
The same PCs have different counts when scoped to node 4.

Reviewed annotations are tied to the B0 ELF hash and reviewed source hashes in
`tools/explorer/reviewed_sources.json`. They distinguish product multiplication,
address multiplication, operand loads, offsets, padding checks, loop control, and
scaling helper bodies. Modified evidence disables annotations. Unreviewed code
remains unclassified. Instruction categories alone are not semantic proof that a
multiply implements a MAC.

### Advanced Analysis

This panel starts closed. It follows the selected function to its matching
compilation unit and opens optimized GIMPLE at that function by default. Select
other stages, search functions, open the full dump, compare adjacent stages, or
inspect the recorded command and dependency hashes. GCC estimates are not Spike
measurements. Linker relaxation can change final assembly addresses; source and
symbol links are correspondence, not instruction-by-instruction IR equivalence.

## Production and portable use

```sh
gmake explorer-build
gmake explorer-serve
```

Development and local preview serving expose only the configured bundle at a known
URL (`/profiles/local.zip`) and advertise its availability through
`/local-profile.json`. A static browser does not read repository paths. The
**Load local B0** button appears only when that configured asset is available.

Production builds omit profile data by default. To package it explicitly:

```sh
gmake explorer-build EXPLORER_INCLUDE_BUNDLE=1
```

The built `explorer/dist/` can be served by an ordinary static HTTP server. All
viewer dependencies and workers are local. Without an included bundle, use file
selection or drag-and-drop. The ZIP is an analysis bundle, not an executable app;
serve the viewer over HTTP rather than opening `index.html` with `file://`.

To export paths explicitly:

```sh
uv run --python 3.12 --with tflite==2.18.0 --with numpy==2.4.3 --with pyelftools==0.32 \
  python tools/export_explorer.py \
  --capture-dir build/profiling/B0 \
  --model models/efficientnet-lite0-int8.tflite \
  --elf build/tflm-profile/rv64imc_rv64imc_release_with_logs_gcc/bin/efficientnet_lite0 \
  --compiler-dir build/explorer/compiler/B0 \
  --output build/explorer/B0.zip
```

## Bundle contract, version 1

`manifest.json` declares `format: riscv-execution-explorer`, `schemaVersion: 2`,
and SHA-256/byte-size records for every other entry. `evidence.json` contains:

| Collection | Identity / relations |
|---|---|
| `graph.nodes`, `graph.tensors`, `graph.edges` | Logical node IDs, tensor relationships, execution-unit IDs and executed/eliminated disposition |
| `events` | Measured scope, execution-unit ID, boundaries/status, inclusive total and `counts[pc]`; optional setup and derived invocation overhead |
| `executionPlan` | Stable ordered units, logical origins, implementation/backend, operands, source regions, work-count policy and supporting artifacts |
| `memoryPlan`, `preparedParameters` | Optional frozen compiler contracts, prepared integers, placement offsets, inclusive lifetimes, aliases and scratch |
| `measurementSummary` | Optional build metrics with explicit scope, unit and measured/derived/unavailable evidence |
| `instructions` | One record keyed by decimal PC, bytes, decode, transfer target, function IDs, inline frames |
| `functions` | Symbol ranges/aliases/linkage names, PC membership, basic blocks, static edges and nested cyclic regions |
| `sources` | Normalized source ID, snapshot archive path, hash, availability/provenance status |
| `compilerUnits`, `compilerEvidence` | Commands, dependency hashes, artifact paths/hashes/function ranges, measured/analysis ELF identities |
| `registers` (optional) | Measured ELF hash, named variables/declarations, half-open PC ranges for locations and symbolic memory relationships, inferred loop roles, and verified compiler-origin links |
| `annotations` | Reviewed explanation, supporting PCs, executable/source hashes |

Addresses and counters are unsigned decimal strings (instruction bits use hex).
Static code, sources, and compiler text are shared across events. Function symbol
ranges can overlap; aliases are preserved and the narrowest containing range is
used for exclusive navigation/count aggregation. Complete code remains available.

Text snapshots live under `sources/`; compiler dumps and the complete compilation
inventory live under `compiler/`. The measured ELF and model weight buffers are
not required in the browser bundle. SHA-256 integrity protects against corruption;
it does not authenticate an archive's author.

The worker rejects unsupported schemas, missing/duplicate/unsafe paths, integrity
failures, invalid references, nonconserving counts, and uint64 overflow. It enforces
256 MiB compressed, 128 MiB per entry, 512 MiB total decompressed, and 10,000 entries.
Decompression limits are checked as output chunks arrive. A failed import keeps
the previous bundle available. Large compiler text is requested on demand.

## Validation

```sh
gmake profile-tests
gmake explorer-tests
npm run build --prefix explorer
npm run test:browser --prefix explorer
```

Python tests compile an RV64 fixture covering nested loops, multiple latches,
irreducible cycles and indirect transfers, and verify real B0 counts when present.
Frontend tests exercise malformed imports, stale annotations, integrity, references,
and counters beyond 53-bit precision. Browser acceptance tests require an exported
B0 and A0 v2 bundles and Playwright's Chromium installation (`npx playwright install chromium`
from `explorer/` if needed); they otherwise skip the local-data scenarios.

This tool makes no cycle, CPI, cache-miss, bandwidth, or hardware speedup claims.
Cross-build comparison and profiling-job launching remain outside this version.


## Unified app with live simulation

For the accepted compiler B1, run `gmake compiler-app-dev` and open
**http://127.0.0.1:5174/**. Both tabs use the matching v2 bundle and saved compiler
ELF. `gmake compiler-app-serve` serves production assets on port 8765.

For LiteRT B0, run `gmake app-serve` and open **http://127.0.0.1:8765/** for the **Explorer** and
**Simulator** tabs with one local backend. `gmake simulator-serve` remains an
alias for this launch workflow. `gmake app-dev` serves both views on port 5174
with hot reload. See [Simulator setup and controls](simulator.md) for matching
artifact prerequisites.

Tab switching preserves the imported profile, navigation, and simulator session.
A running simulation continues in the background, with its status shown on the
Simulator tab. Execution shortcuts only apply while that tab is visible.
`gmake explorer-dev` and `gmake explorer-serve` remain useful for offline profile
viewing; the Simulator tab needs the local backend.
