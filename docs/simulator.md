# Execution Atlas: Simulator tab

Execution Atlas has **Explorer** and **Simulator** tabs in one app. The Simulator
is an assembly debugger for the pinned, single-hart RV64IMC EfficientNet program.
The debugging panes run left to right as **Assembly → C++ → Model**, with
assembly taking half the workspace initially. Resize adjacent panes by dragging
the separators or focusing one and pressing the arrow keys.

Switch tabs without losing your profile selection, paused PC, registers, or
breakpoints. Execution and profile navigation remain independent. A running
simulation continues when you switch to Explorer; its tab shows **RUNNING** (or
**PAUSED** after it stops). F8/F10 control execution only in the Simulator tab.

## Start locally

Install the viewer dependencies once with `(cd explorer && npm ci)`.

The matching debug ELF and exported bundle must already exist. A fresh checkout
can build them with `gmake rv64-profile`, then regenerate the profiling capture
with `gmake profile-spike` or import the matching capture, and run
`gmake explorer-export`. Starting the debugger never starts a profiling capture.

```sh
gmake app-dev
```

Open **http://127.0.0.1:5174/** and choose **Simulator**. The first invocation
builds an isolated debug simulator; subsequent invocations reuse its build.
The backend listens on port 8765. Both views use this app URL; an existing viewer on port 5173 remains untouched.
Stop the supervising command with Ctrl+C to stop the frontend and backend.
Only one browser window may own a simulator session at a time.

For a production build served locally:

```sh
gmake app-serve
```

Open **http://127.0.0.1:8765/**. One backend serves both tabs and the simulation API.
The existing `gmake simulator-serve` and `gmake simulator-dev` commands also launch
the unified app. The legacy `/simulator.html` URL opens the Simulator tab directly;
`/#simulator` is its new direct link. `PROFILE_CONFIGURATION` selects the
bundle and evidence configuration, as for the profile tools. The ELF and model
must match that bundle exactly. Generated files stay in ignored build directories.

## Controls

- **Start** executes initialization and stops before inference entry.
- **Step** / **F10** executes one instruction. **Continue** / **F8** runs until a
  breakpoint, an inference boundary, a trap/wait, or program exit. **Pause** / F8
  interrupts an active run. Retirements count successful instructions, including
  compressed instructions, once; serialization retries are separate.
- Choose a destination node, then press **Run to stage**. This installs a temporary
  breakpoint on the operator callback entry conditioned on the model-node index.
  Layers sharing a kernel therefore remain distinct. A destination already entered
  restarts the same deterministic input and replays. Earlier layers really execute
  to produce its input tensors. Pause cancels the current run without changing the
  chosen destination; Continue resumes toward it.
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
  displays the reference-checksum verification result.

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
