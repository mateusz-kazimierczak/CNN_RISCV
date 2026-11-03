# Execution Atlas: Simulator tab

Execution Atlas has **Explorer** and **Simulator** tabs in one app. The Simulator
is an assembly debugger for the pinned, single-hart RV64IMC EfficientNet programs,
including standalone compiler A0/B1 and LiteRT B0. It consumes schema-v2 bundles.
The debugging panes run left to right as **Assembly → C++ → Model**, with
assembly taking half the workspace initially. Resize adjacent panes by dragging
the separators or focusing one and pressing the arrow keys.

Switch tabs without losing your profile selection, paused PC, registers, or
breakpoints. Execution and profile navigation remain independent. A running
simulation continues when you switch to Explorer; its tab shows **RUNNING** (or
**PAUSED** after it stops). F8/F10 control execution only in the Simulator tab.

## Start locally

### Accepted compiler B1

```sh
npm ci --prefix explorer  # once, if dependencies are not installed
gmake compiler-app-dev
```

Open **http://127.0.0.1:5174/#simulator**. The Explorer tab loads the same accepted
B1 bundle. This command builds only the isolated host debugger; it does not rebuild
B0, the compiler model, or a profiling capture. It reads the immutable ELF from
`build/compiler/B1-spatial2-oc2/rv64/build.json` and verifies it against
`build/explorer/B1-spatial2-oc2.zip`. Stop the supervising command with Ctrl+C.

For production assets served by one backend, run `gmake compiler-app-serve` and
open **http://127.0.0.1:8765/#simulator**.

Choose another saved compiler build explicitly, for example:

```sh
gmake compiler-app-dev \
  COMPILER_SIMULATOR_CONFIGURATION=A0 \
  COMPILER_SIMULATOR_BUILD=build/compiler/A0/rv64/build.json \
  COMPILER_SIMULATOR_BUNDLE=build/explorer/A0.zip
```

The configuration names the local asset. The bundle's adapter and execution plan
select the execution path; the label never implies a backend. Model, ELF and
bundle hashes must match. Generate a missing bundle with the manifest-driven
`tools/profile_compiler.py export` workflow in [compiler-profiling.md](compiler-profiling.md).
Custom bundle filenames can also be opened with the Explorer's file picker.

### LiteRT baseline (evaluation A0)

After a completed midterm benchmark, the LiteRT profile is named `midterm-A0`.
Export its matching bundle and start the combined app:

```sh
npm ci --prefix explorer
gmake explorer-export PROFILE_CONFIGURATION=midterm-A0
gmake app-dev PROFILE_CONFIGURATION=midterm-A0
```

Open **http://127.0.0.1:5174/#simulator**. The backend listens on port 8765;
both Explorer and Simulator use the app on 5174. An existing offline viewer on
5173 is unaffected. Ctrl+C stops the frontend and backend. Only one browser
window owns a simulator session at a time.

For production assets served by one backend:

```sh
gmake app-serve PROFILE_CONFIGURATION=midterm-A0
```

Open **http://127.0.0.1:8765/#simulator**.

Historical LiteRT captures/bundles use configuration `B0`, which also denotes
evaluation A0. With those matching artifacts available, the equivalent launch
is `gmake app-dev PROFILE_CONFIGURATION=B0`. The configuration selects the
bundle/evidence directory; it does not change the executed model or ISA.

The debug ELF, model and bundle hashes must match. Starting the debugger builds
only the isolated host simulator and never starts a profiling capture. The
[midterm benchmark](midterm-submission.md#reproduce-the-evaluation) generates a
fresh LiteRT profile. The original profiling workflow is documented in
[profiling.md](profiling.md).

`simulator-dev` and `simulator-serve` are aliases for the unified app workflow.
The legacy `/simulator.html` URL opens the Simulator tab directly. Generated
files remain under ignored build directories.

## Execution evidence

The v2 reader validates archive paths, inventory, SHA-256 integrity, resource
limits, unsigned 64-bit counts and per-PC conservation. It compares the complete
bundle disassembly with the linked ELF and resolves compiler unit symbols before
launch. Allocation is optional and absent for compiler A0/B1. Unit attribution is
inclusive of callees, including tail returns; nested or unexpected entries,
missing units and nonzero inference status stop with an attribution error.

The native debugger tracks execution positions, not logical node indices. Public
snapshots include `unitIndex`, `unitId`, `nodeIds`, and last-entered origins. A shared
unit has no single logical `node`. Graph costs remain recorded profile evidence;
registers and retirements are live architectural state. Native commands accept
`unit` destinations; the older `node` command field is retained as a stage-index
alias for existing clients. Version-1 bundles must be regenerated.

The debug engine currently supports RV64IMC (and the standard CSR instructions
used by its fixtures). Custom-ISA builds need a matching debug engine and adapter.

## Controls

- **Start** executes initialization and stops before inference entry.
- **Step** / **F10** executes one instruction. **Continue** / **F8** runs until a
  breakpoint, an inference boundary, a trap/wait, or program exit. **Pause** / F8
  interrupts an active run. Retirements count successful instructions, including
  compressed instructions, once; serialization retries are separate.
- Choose an execution unit, then press **Run to stage**. The debugger checks
  observed unit entry/order against the saved schedule. Repeated calls to the same
  implementation retain separate destinations and conditioned breakpoints. The
  LiteRT adapter additionally validates the interpreter's graph index.
  Split logical nodes expose each unit in the selector; shared units highlight all
  their logical origins. Clicking a graph node selects its first observed unit.
  Eliminated nodes have no execution destination. Incomplete observed schedules
  are rejected before launch. A destination
  already entered restarts the same deterministic input and replays. Earlier units
  execute to produce its runtime inputs. Pause stops execution without discarding the destination;
  Continue resumes toward the destination. Persistent breakpoints survive replay.
- Click the margin beside an assembly line number, press **F9** with assembly
  focused, or use **Break at selection**, to toggle an address breakpoint. A faint
  red dot on gutter hover previews the click target. Breakpoints can be prepared
  before Start; pause an active run to edit them. Symbol headings, gaps, and ROM
  rows cannot receive breakpoints. A red circle marks an address breakpoint; a
  diamond marks a stage-entry breakpoint on a shared callback address.
  A separate yellow arrow and highlighted line mark the **next instruction to
  execute** while paused, even when browsing other code. During execution, a gray
  arrow marks the **last stop**, not a live trace. Breakpoints and the PC use
  separate, fixed-width gutter lanes so they can coexist without shifting code.
  The Breakpoints drawer also supports **Break on stage entry**.
  Persistent breakpoints survive restart and can interrupt replay before its
  destination. Continue executes the current breakpoint instruction once before
  permitting another hit at that address.
- The model highlights the active operator, including execution in its helper
  functions. Clicking another node changes the run destination only. Model counts
  and coloring are explicitly the recorded profile; they are not live counters.
- Assembly/source browsing does not move execution. **Follow PC** returns to the
  paused instruction; execution controls follow the next stop automatically.
  Assembly is one address-ordered listing of all decoded executable code, including
  initialization, inference helpers, output checks, and code a run may never execute.
  Function headers mark boundaries. **Jump to function** and the hexadecimal address
  field scroll within this listing; they do not filter it or move the live PC.
  Source-line selections highlight every matching instruction throughout the program,
  including inline mappings. The model's active operator stays tied to live execution;
  shared kernel addresses do not identify a unique model layer.
- Click a register or instruction to reuse the evidence explanations. Numeric
  register values are live only at the paused PC. Other rows show static evidence,
  never fabricated historical values. Register changes compare consecutive stops
  and clear on restart. Source-variable help describes model/source evidence; it
  does not evaluate optimized C++ variables at runtime.
- The Memory drawer reads up to 4096 bytes of configured RAM. Addresses and values
  are exact 64-bit quantities; MMIO, writes, and out-of-range reads are rejected.
- On inference completion, Continue runs output checking and exits. Program output
  displays the verification result. Compiler targets print every output byte;
  the backend requires all 1,000 bytes to match the saved output SHA-256 as well as
  the expected checksum, successful process exit and completed invocation.

A source line is a best-effort DWARF mapping, not a source execution timeline.
Traps report both the faulting instruction and the handler PC; handler execution
has not begun. Startup ROM/unmapped locations retain native disassembly and live
state. The pinned Spike reset ROM contributes a bounded five-instruction window
once a session starts. ROM padding, its entry-point pointer, DTB, model weights,
and other non-code data are excluded; address gaps are explicit. Unknown locations
retain the current backend-decoded instruction. Breakpoints are supported on the
verified ELF instructions. A wait may require an external event; Restart is available
if none exists.

The program text, address-to-row map, branch links, and source-line index are built
once per loaded executable (or when supplementary native code changes). Stops update
selection and breakpoint/source decorations without replacing the editor's text.
This is a static code view with a live PC, not an execution trace.

## Backend and isolation

`tools/spike_debug/build.py` builds a separate clone of the pinned Spike revision,
using the tracked patch and headers. It refuses unexpected tracked dependency
changes. The ordinary and profiling simulator installations remain separate.
The debug target uses the same measured program bytes and input. Artifact hashes
are rechecked for every new run. Each guest loads a verified private ELF/config
snapshot, so rebuilding the workspace executable cannot change a paused session.
If artifacts change, export matching evidence and restart the backend.

The Python `aiohttp` backend exposes `/api/simulator/status`,
`/api/simulator/evidence`, and `/api/simulator/ws`. The WebSocket requires the
status endpoint's session token and a local allowed origin. Host and origin
checks, fixed server-side artifact paths, and loopback binding constrain access.
The browser cannot supply a shell command or arbitrary executable/file path.

The backend supervises a native process with a private inherited socket.
Bounded typed commands drive execution, breakpoints, snapshots, and memory;
JSON records report state. Program stdout/stderr use separate pipes. Native
execution returns to the normal HTIF scheduler between batches, including before
reporting a guest wait, so output and pending exit requests are serviced.

Snapshots describe state **before the next instruction**. Protocol version 1 uses
strings for register values, addresses, and counts. Request IDs correlate replies;
session generations discard previous-process messages during restart. Disconnect
and server shutdown terminate the guest process. There is no background profiling
job, full instruction trace, backward execution, or checkpoint restore.

## Verify

```sh
gmake simulator-tests
SPIKE_DEBUG_FULL_B0=1 gmake simulator-tests
```

The small compiled fixtures exercise compressed instructions, branch re-entry,
helper calls, stage identity, replay, pause, traps, waits, serialization, RAM bounds,
and WebSocket ownership/security/cleanup. The opt-in full acceptance additionally
checks Node 4's loop, exactly **4,867,278,370** inference retirements, and checksum
**0x4b6a91e2**. Its stopped-state evidence is saved to
`build/simulator/B0/acceptance.json`. Existing profiling/explorer tests remain
available through their original Make targets. Browser checks use the unified
app and a running backend.


## Debugger interaction references

The margin click / F9 convention follows [VS Code debugging](https://code.visualstudio.com/docs/debugtest/debugging)
and the address-based breakpoint column in [Ripes](https://github.com/mortbopet/Ripes/blob/master/docs/introduction.md).
The fixed gutter and separate PC/breakpoint lanes address feedback about
[code shifting when gutter icons appear](https://github.com/microsoft/vscode/issues/193703)
and [icons hiding breakpoint feedback](https://github.com/microsoft/vscode/issues/25174).
Keeping the C++ and model context beside assembly also follows feedback about
[losing context while switching simulator views](https://github.com/mortbopet/Ripes/issues/408).

## V2 validation

```sh
gmake compiler-simulator-tests
# Full real inference gates (slower; no model rebuild or profiling capture):
SPIKE_DEBUG_FULL_B0=1 SPIKE_DEBUG_FULL_B1=1 gmake compiler-simulator-tests
# With compiler-app-dev running in another terminal:
cd explorer
SIMULATOR_V2_BROWSER_URL=http://127.0.0.1:5174/#simulator \
  npm run test:browser -- tests/simulator-v2.spec.ts
```

Hand-counted native fixtures exercise shared entries, callees, compressed
instructions, tail returns, serialization, traps, invalid order, missing units,
nonzero status, replay and conditioned breakpoints. The real-B1 gate checks exact
full-invocation retirements and complete output evidence. The B0 gate retains the
original loop/register checks and exact full-inference instruction count.
