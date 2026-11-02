# Running B0 and software B1 on CV-Wally

For the accepted submission comparison across B1 and X1–X5, use
[the hardware-era progression](hardware-optimization-report.md) and
[validated cycle table](../results/profiling/hardware-progression/README.md).
Main X1 is `X1-tile2x4`, main X2 is `X2-optimized`, and X5 reuses X4's hardware.
Intermediate compiler stages and D1 have no separately recorded full-model cycles.

This work runs the **preserved B0 and accepted software B1 executables** on the
same CV-Wally core in Verilator. It adds no instruction extension or synthesis
flow. Simulation cycles and retirements are hardware-model results; the
testbench clock period does not establish a physical clock frequency.

The separate [Xqmac8 RTL overlay](cvw-xqmac8.md) adds the first custom instruction.
Its preparation and tests leave this B0/B1 overlay and pinned sources unchanged.

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
passed all output and retirement gates: B0 took 5,397,408,750 invocation cycles
and software B1 took 1,679,179,098. See the tracked `results/cvw/` summary for
evidence; raw logs and binaries stay in ignored build storage.

Physical Fmax, area and synthesis results are outside this checkpoint and remain
unmeasured. B0 and B1 use the same hardware configuration.

The combined [Xqmac8/Xrequant RTL overlay](cvw-xrequant.md) adds the second instruction, precise descriptor traps and X2 compiler replay while preserving these baseline runs.

## Custom-instruction full inference

The full-model checkpoints use **X1-tile2x4** on the Xqmac8-only core and
**X2-optimized** on the combined Xqmac8/Xrequant core. They retain the accepted
linked ELFs rather than rebuilding them with the Linux toolchain. The base core,
cache and memory configuration comes from the same pinned RV64I configuration
and overrides as B0/B1. Custom units are combinational; cycle reductions do not
establish equal achievable physical clock frequencies.

`tools/cvw/export_custom_inputs.py` verifies the immutable build snapshots,
canonical input/output evidence, both identical Spike captures, and every PC
before exporting the two ELFs. It derives invocation entry from the saved plan,
the return site from the linked `jal`, and the output address from the unique
`a0_output` AUIPC/ADDI pair. Its tracked `custom_workloads.json` records ELF and
capture identities, address evidence, and exact expected retirement counts:

| Checkpoint | Total instructions | Xqmac8 | Xrequant |
|---|---:|---:|---:|
| X1-tile2x4 | 594,975,670 | 42,317,184 | 0 |
| X2-optimized | 436,158,109 | 42,317,184 | 7,369,032 |

`prepare_full_custom.py` creates separate `build/cvw/full-xqmac8` and
`build/cvw/full-xrequant` overlays. It preserves the baseline and kernel-test
overlays, appends host-only custom retirement instrumentation to the ordinary
inference monitor, and saves hashes of owned RTL, configuration and monitors.
Total cycles/instructions retain the B0/B1 boundary. Per-extension counts use
the same commit predicate and exact encoding masks; unexpected traps, unknown
custom encodings and count mismatches reject the run.

The Windows execution checkout is `/home/mat/code/arch_project-custom`; installed
Verilator and pristine upstream RTL are shared with the baseline checkout.
Copy the current project scripts, `rtl/cvw/`, exported input files and workload
contract there before launch. Large Verilator builds remain on Windows.

```sh
python3 tools/cvw/export_custom_inputs.py
python3 tools/cvw/launch_windows.py --host mateu@100.120.151.72 \
  --project /home/mat/code/arch_project-custom --suite custom \
  --run-label custom-20261018
python3 tools/cvw/collect_custom.py --host mateu@100.120.151.72 \
  --run-label custom-20261018
```

Use a fresh run label for each new suite. A Windows-owned WSL process remains
alive through both simulator builds, preflight gates and parallel full runs.
Each exact inference testbench first runs a hand-counted fixture (25 instructions
on X1, 27 on X2), complete unaligned output comparison and custom-result checks.
Wrong total count, wrong custom count and incomplete execution must each fail.
Both preflight suites must pass before either model launches.

Acceptance requires a clean application/testbench exit, all 1,000 reference
output bytes, exact total retirements and exact per-extension retirements.
`collect_custom.py` checks the remote output bytes, contract, ELF and simulator
identities before publishing completed metrics. Partial progress stays separate.
Compact results are in `results/cvw/full-custom/`; raw run records and outputs
remain in ignored remote build storage, with collected snapshots under local
`build/cvw/remote/`. `python3 -m unittest tools.cvw.test_full_custom -v` checks
boundary decoding and rejection of inconsistent completion evidence.

### Xpostinc full inference

The separate X3 suite runs the accepted **X3-selected** checkpoint, with all three
extensions enabled, in `/home/mat/code/arch_project-xpostinc`. Its ELF hash is
`638d7096b8fce3fffddf041c778a9d23635db22aaf90fea4150dee2be495b8c0`.
The independently verified Spike capture expects 423,520,020 total retirements:
42,317,184 Xqmac8, 7,369,032 Xrequant, 12,228,384 post-increment loads and
1,405,632 post-increment stores. Load and store counts remain separate.

```sh
python3 tools/cvw/export_custom_inputs.py --configurations X3 \
  --output build/cvw/postinc-inputs --contract tools/cvw/postinc_workloads.json
python3 tools/cvw/launch_windows.py --host mateu@100.120.151.72 \
  --project /home/mat/code/arch_project-xpostinc --suite postinc \
  --run-label postinc-20261018
python3 tools/cvw/collect_custom.py --host mateu@100.120.151.72 \
  --project code/arch_project-xpostinc --configurations X3 \
  --contract tools/cvw/postinc_workloads.json --output results/cvw/full-postinc \
  --run-label postinc-20261018
```

Transfer the current CV-Wally scripts, three RTL patches, arithmetic RTL modules,
workload contract and exported input files before launch. Existing baseline,
X1/X2 and kernel-replay overlays remain separate. The Windows-owned job first
checks a 38-instruction fixture with all three extensions, including memory
values and both post-increment pointer updates. Wrong total, arithmetic-custom,
and post-increment counts must each reject; incomplete execution must reject.
Only after these gates pass does it start the full unchanged ELF. Complete
output and exact per-class retirement reconciliation remain mandatory before
publishing inference cycles. Results are saved in `results/cvw/full-postinc/`.

### Xdwmac8 full inference

The X4 suite runs the verified **X4** compiler checkpoint on the combined
Xqmac8/Xrequant/Xpostinc/Xdwmac8 core in the separate Windows WSL checkout
`/home/mat/code/arch_project-xdwmac8`. It preserves all earlier simulation
executables, configurations and results. The original ELF identity is
`81efdf6e7f268559a881c5f20a5c307f30fd983d050980f355f8236fccd03b2a`.
Its repeated Spike profiles contain 229,114,977 total instructions, including
3,831,052 bank MACs and 288,316 of each of the four set and four get forms.
All nine bank counters reconcile independently, alongside the earlier custom
arithmetic and post-increment counters. The unknown/reserved encoding checks
use the exact architectural operand-field masks.

```sh
python3 tools/cvw/export_custom_inputs.py --configurations X4 \
  --output build/cvw/dwmac-inputs --contract tools/cvw/dwmac_workloads.json
python3 tools/cvw/launch_windows.py --host mateu@100.120.151.72 \
  --project /home/mat/code/arch_project-xdwmac8 --suite dwmac \
  --run-label dwmac-20261018
python3 tools/cvw/collect_custom.py --host mateu@100.120.151.72 \
  --project code/arch_project-xdwmac8 --configurations X4 \
  --contract tools/cvw/dwmac_workloads.json --output results/cvw/full-dwmac \
  --run-label dwmac-20261018
```

Transfer the scripts, four patches, RTL modules, bank encoding contract, workload
contract and exported inputs before launch. The Windows-owned suite builds the
full testbench and checks a 54-instruction fixture before launching inference.
That fixture initializes all bank pairs, performs a nonzero MAC and checks every
get result, in addition to the earlier arithmetic, memory and pointer checks.
All 1,000 output bytes must match. Incorrect total, arithmetic, postincrement
or individual bank-form counts and incomplete runs must reject. A passing
inference still requires the same full output and exact retirement evidence;
results are saved separately in `results/cvw/full-dwmac/`.

### X5 on the unchanged X4 hardware

X5 changes only the software stem convolution. Its original ELF hash is
`75f2eddf7de3b165b7ab80733f18eafa3b197315622686289ab5ccaa8d16f8d6`,
and its verified repeated Spike captures contain 167,729,178 instructions.
The packed stem raises total Xqmac8 use to 43,922,816; all other custom
instruction counts remain those of X4.

The separate `/home/mat/code/arch_project-x5` checkout links to the existing
`arch_project-xdwmac8/build/cvw/full-xdwmac8` overlay and compiled simulator.
It does not prepare or rebuild RTL. `reuse_hardware.py` checks the integration,
owned sources, original preflight ELF and six gates, then saves an explicitly
labeled reuse record. These are reused X4 fixture results, not new X5 fixture
executions. The runner checks the compiled simulator hash before and after
inference and rejects a changed executable. Full output comparison and all
thirteen custom instruction counters still apply to the new X5 ELF.

```sh
python3 tools/cvw/export_custom_inputs.py --configurations X5 \
  --output build/cvw/x5-inputs --contract tools/cvw/x5_workloads.json
# Transfer scripts/inputs and link the existing X4 overlay before launch.
python3 tools/cvw/launch_windows.py --host mateu@100.120.151.72 \
  --project /home/mat/code/arch_project-x5 --suite x5 --run-label x5-20261018
python3 tools/cvw/collect_custom.py --host mateu@100.120.151.72 \
  --project code/arch_project-x5 --configurations X5 \
  --contract tools/cvw/x5_workloads.json --output results/cvw/full-x5 \
  --run-label x5-20261018
```

X4 and X5 retain separate program memory images, test lists, process records,
model logs and outputs. Results are published in `results/cvw/full-x5/` only
after complete correctness and retirement validation.
