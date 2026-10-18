# Running B0 and software B1 on CV-Wally

This work runs the **preserved B0 and accepted software B1 executables** on the
same CV-Wally core in Verilator. It adds no instruction extension or synthesis
flow. Simulation cycles and retirements are hardware-model results; the
testbench clock period does not establish a physical clock frequency.

## Execution host

Use the Windows workstation's Ubuntu-22.04 WSL2 distribution. The inspected
machine has an Intel Core Ultra 9 275HX, approximately 64 GB physical RAM,
24 CPUs visible to WSL and approximately 31 GiB available to that VM. Keep
sources and build products under `/home/mat/code/arch_project`, in the Linux
filesystem. The Mac is the editing/reporting host.

Windows OpenSSH can start Linux commands directly. The project helper transports
bash on stdin, avoiding nested PowerShell/cmd quoting:

```sh
python3 tools/cvw_remote.py --host "$CVW_HOST" <<'BASH'
set -eu
cd ~/code/arch_project
bash tools/cvw/run_suite.sh
BASH
```

Set `CVW_HOST` to the workstation's SSH destination. The distribution defaults
to `Ubuntu-22.04`; `--distribution` selects another one. `--upload PATH` copies
a specified project-relative file to the corresponding path under the WSL
project before executing the script. It does not synchronize the working tree
or discard remote changes.

For long runs, use the Windows-owned launcher:

```sh
python3 tools/cvw/launch_windows.py --host "$CVW_HOST" --run-label baseline-1
```

It starts `wsl.exe` through Windows' local process-creation service, independently
of the SSH session's lifetime. The Windows process holds WSL open until
`windows_suite.sh` and both runners finish. No scheduled task, persistent service,
registry change or administrator installation is created. Linux-side logs are
under `build/cvw/runs/windows-baseline-1.log`. Process creation alone is not a
passing test; use the collector to verify the Linux runner records.

Initial detached Linux jobs vanished when their launching Windows session ended.
They were marked interrupted. A normal foreground SSH run remains useful, but
must stay connected until completion. A `RUNNING` record with no live process is
interrupted, not a passing result. The collector checks this explicitly.

## Pinned dependencies and configuration

| Component | Selection |
|---|---|
| Wally | `712ee9719467e9e9987cebd55926ae8e01b08770` |
| Verilator | v5.046, `24b2ac24c721fdad89bba75a492e02c6aa63f32e` |
| Workload ISA/ABI | RV64IMC / LP64 |
| Core configuration | `arch_project_rv64imc`, derived from pinned `rv64i` |
| Standard monitoring support | CSR, fence.i and performance counters enabled |
| Excluded execution features | Floating point, atomics, vector, bit manipulation and crypto |
| L1 I-cache / D-cache | 16 KiB each, four ways, 64-byte lines |
| Branch prediction | Enabled; upstream gshare parameters retained |
| Integer divide | Upstream four bits/cycle configuration |
| RAM | 128 MiB modeled uncore RAM at `0x80000000`, zero configured extra RAM latency |
| Reset | `0x80000000`; existing workload stack top `0x88000000` |

The RAM size accommodates the existing Spike ELF layout, including its stack
reservation. It is a simulation provision, not a claim that 128 MiB is on-chip.
The small boot ROM is enabled because the upstream testbench references its
hierarchy in procedural boot-mode branches; these runs reset directly into RAM.
No boot image or OS is loaded. All baseline choices are explicit in the generated
`build/cvw/wally/integration.json`.

`prepare.py` verifies the pinned checkout and creates a separate overlay under
`build/cvw/wally/`. The synthesizable RTL is linked unchanged from `.deps/cvw`.
The overlay contains the selected configuration, a copy of the upstream testbench
with one project-monitor include, and that monitor. Downloaded tracked sources
are not edited in place.

## Installation and input transfer

On a fresh Ubuntu host, install the packages listed in
`tools/cvw/install-deps.sh`, then run:

```sh
bash tools/cvw/bootstrap.sh
```

This fetches the pinned source revisions, builds Verilator into `.deps/verilator`,
and prepares the overlay. It does not install the full Wally toolchain, FPGA
tools, Linux images, commercial verification software or synthesis libraries.
Initial Verilator build output is saved in `build/cvw/verilator-build.log`.

On the machine retaining the accepted compiler/Spike artifacts, export the
unchanged executables and the independent expected public output:

```sh
python3 tools/cvw/export_inputs.py \
  --expected-output build/profiling/compiler/ae2e34b227a93a4004fd5f68408f772581619aaf6a1a2ac0ed73cb54817a33de/expected-output.bin
```

The default B0 source is its original TFLM ELF and the B1 source is
`build/compiler/B1-spatial2-oc2/rv64/a0.elf`. Explicit `--b0` and `--b1` paths may
point at restored copies. All three hashes must match `tools/cvw/workloads.json`
before any output is copied. The exported set contains weights because these
are executable workloads; keep it in ignored build storage.

Transfer `build/cvw/inputs/B0.elf`, `B1.elf` and `expected-output.bin` to the same
relative directory on WSL. For example:

```sh
python3 tools/cvw_remote.py --host "$CVW_HOST" \
  --upload build/cvw/inputs/B0.elf \
  --upload build/cvw/inputs/B1.elf \
  --upload build/cvw/inputs/expected-output.bin <<'BASH'
set -eu
cd ~/code/arch_project
sha256sum build/cvw/inputs/*
BASH
```

| Workload | Preserved ELF SHA-256 | Expected invocation retirements |
|---|---|---:|
| B0 | `480473165dfaa8185e3446dd679434727055b3e5064bae5f5736175a009bbeb6` | 4,867,278,370 |
| B1 | `d9f1f72d52c386f39edb5f4b331c5d6b0351f26f18dfa50daa0d1e6fcc5914d9` | 1,576,585,275 |

Neither program is relinked for Wally. The frozen B0 files, accepted B1 kernels,
numerical parameters, input generator and invocation bodies remain unchanged.

## Directed bring-up gate

Inside the Linux project checkout:

```sh
make cvw-smoke
```

The assembly fixture checks signed multiplication, compressed instructions,
RAM load/store, branches and calls/returns. Its measured function executes
**19 instructions**, independently confirmed by the existing Spike retirement
collector. The fixture fills an unaligned 1,000-byte buffer after the measured
function, leaves dirty cache lines, sends two acknowledged console characters,
and exits through HTIF.

The host comparison verifies all 1,000 bytes, including unaligned first/last
words. It also exercises recovering an output pointer from the actual linked
load result, the mechanism used for frozen B0. Negative runs require rejection
of an incorrect expected count and a cycle-limited incomplete execution.
Logs and gate results are written to `build/cvw/smoke/`.

The reproducible fixture measured 19 retirements and 35 cycles in the
declared commit interval. Those cycles belong to this fixture and configuration,
not the model.

## Full inference and acceptance

```sh
make cvw-b0 CVW_RUN_LABEL=baseline-1
make cvw-b1 CVW_RUN_LABEL=baseline-1
# Or supervise both independent simulations concurrently:
make cvw-run CVW_RUN_LABEL=baseline-1
```

Each fresh output directory contains `run.json`, `simulation.log`, `metrics.json`
and `output.bin`. Existing run directories are rejected rather than replaced.
The first simulation compiles Wally; later runs reuse the same binary. Runtime
waveform recording is disabled. Each simulator currently uses one CPU thread;
parallel build jobs are separate from simulation threading.

Acceptance requires all of:

- Preserved input ELF and expected-output hashes.
- Unmodified pinned Wally RTL and matching overlay hashes.
- Exactly one complete invocation with the expected Spike retirement total.
- No unexpected trap, cycle-limit stop or incomplete program.
- Application success and upstream testbench success through clean HTIF exit.
- Exact comparison of **all 1,000 public output bytes** with the verified oracle.

`run.json` reports `PASS` only after these checks. It records the simulator
binary identity, integration choices, actual command, cycle/retirement counts,
exact CPI fraction and output hash. A nonzero process exit or validation error
records `FAIL`. A hard host/session interruption may leave `RUNNING`; check live
processes and preserve it as interrupted evidence. The runner's wall timeout
terminates its simulator process group rather than leaving orphaned jobs.

From the editing host, collect a small result/progress snapshot without copying
the simulator or model payloads:

```sh
python3 tools/cvw/collect.py --host "$CVW_HOST" --run-label baseline-1
```

This updates `results/cvw/baseline/summary.json` and its README. Incomplete model
counts remain unavailable; progress lines retain their separate scope. Raw
collected run records are saved under `build/cvw/remote/`.

The runner's wall duration includes program setup, validation and any required
compilation. It is not target execution time. The authoritative model-cycle
measurement excludes setup, stack painting, output checking and printing.

## Measurement and host-interface details

The monitor uses Wally's `minstret` commit predicate: valid M-stage instruction,
no writeback stall, and no writeback flush. It starts when the invocation entry
commits, counts that instruction, and stops before the caller's return-site
instruction commits. The returning instruction and all callees are included.
Its cycle interval includes intervening pipeline stalls and return-redirection
effects. The convention is saved in each metrics file. No instructions are
inserted into the target. These are isolated full program runs with cache state
produced by their ordinary setup, not deliberately warmed-kernel benchmarks.

The upstream testbench prints HTIF console stores but does not acknowledge
software that polls the mailbox. The project monitor models immediate host
consumption by overriding only **load writeback data for the ELF's `tohost`
address** to zero. It does not override ordinary loads, change cached model
data, or edit core RTL. Any mailbox access inside the measured invocation is
fatal. The directed fixture verifies repeated acknowledged writes. Host console
service runs outside measured inference; it is not a hardware acceleration.

B1's output address is established by its saved memory plan and linked
`a0_output` instructions. B0's original application prints aggregate fields;
for stronger validation, a hash-bound probe observes its actual `output->data`
load after Invoke, then captures the load result at writeback. The runner checks
the instruction bytes as well as the ELF hash. It does not infer an output
address from the expected output values.

At program completion, the monitor copies the output range from modeled RAM,
then uses the upstream dirty-cache projection into `ShadowRAM`. The coherent
result is dumped after the projection. Complete byte comparison occurs on the
host. This leaves B0's target executable unchanged while validating more than
its checksum.

## Current evidence

The Windows bring-up passed the 19-instruction fixture, HTIF acknowledgement and
exact 1,000-byte unaligned dirty-cache output comparison. Full B0/B1 executions
have been launched under an independent Windows-owned supervisor. Full-model cycle/CPI results
remain pending until their completion and output gates pass. See the tracked
`results/cvw/` summary for the latest recorded state; raw logs and binaries stay
in ignored build storage.

Physical Fmax, area and synthesis results are outside this checkpoint and remain
unmeasured. B0 and B1 use the same hardware configuration.
