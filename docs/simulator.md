# Spike Studio: live simulation

Spike Studio is a standalone assembly debugger for the pinned, single-hart
RV64IMC EfficientNet program. Open it directly; the profile explorer does not
launch it or share navigation state with it.

## Start locally

The matching debug ELF and exported bundle must already exist. A fresh checkout
can build them with `gmake rv64-profile`, then regenerate the profiling capture
with `gmake profile-spike` or import the matching capture, and run
`gmake explorer-export`. Starting the debugger never starts a profiling capture.

```sh
gmake simulator-dev
```

Open **http://127.0.0.1:5174/simulator.html** in a new window. The first invocation
builds an isolated debug simulator; subsequent invocations reuse its build.
The backend listens on port 8765. These servers do not replace the explorer on
port 5173. Stop the supervising command with Ctrl+C to stop both debugger servers.
Only one browser window may own a simulator session at a time.

For a production build served locally:

```sh
gmake simulator-serve
```

Open **http://127.0.0.1:8765/simulator.html**. `PROFILE_CONFIGURATION` selects the
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
- Click the assembly glyph gutter, or **Break at selection**, to toggle an address
  breakpoint. The Breakpoints drawer also supports **Break on stage entry**.
  Persistent breakpoints survive restart and can interrupt replay before its
  destination. Continue executes the current breakpoint instruction once before
  permitting another hit at that address.
- The model highlights the active operator, including execution in its helper
  functions. Clicking another node changes the run destination only. Model counts
  and coloring are explicitly the recorded profile; they are not live counters.
- Assembly/source browsing does not move execution. **Follow PC** returns to the
  paused instruction; execution controls follow the next stop automatically.
  Source-line selections highlight every matching instruction in the current
  function, including inline mappings. Functions include their complete assembly.
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
state. A wait may require an external event; Restart is available if none exists.

## Backend and isolation

`tools/spike_debug/build.py` builds a separate clone of the pinned Spike revision,
using the tracked patch and headers. It refuses unexpected tracked dependency
changes. The ordinary and profiling simulator installations remain separate.
The debug target uses the same measured program bytes and input.

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
available through their original Make targets. Browser checks use the standalone
page and a running backend.
