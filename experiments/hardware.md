# Hardware-era experiment workflow

[hardware.json](hardware.json) defines the comparison graph and complete compiler
options. It starts from the preserved accepted B1 and certifies that the
B1.7 software checkpoint has identical loaded bytes and memory layout.

For the midterm, use `gmake midterm-tests`, `gmake midterm-benchmark` and
`gmake midterm-report`; see [the midterm guide](../docs/midterm-submission.md).
They reuse this same ISA comparison graph without reading RTL snapshots or
requiring PPA. The `hardware-*` workflow below additionally validates the
full-project RTL evidence and retains its separate requirements.

| Submission label | Retained source checkpoint(s) | Meaning |
|---|---|---|
| X1 | X1.1 `X1`; X1.2 `X1-weights8`; X1.3 `X1-acc64`; X1.4 `X1-tile2x4` | New packed MAC followed by alignment, register-width and tile tuning |
| X2 | X2.1 `X2`; X2.2 `X2-submission-02-outline`; X2.3 `X2-optimized` | New requantization followed by selected outlining and wide ADD registers |
| X3 | `X3-selected`; alternative `X3` is X3.broad | Selected post-increment use; broad and selected share the same X2 parent |
| D1 → X4 | `D1` → `X4` | Separate software zero-point correction from the depthwise accumulator-bank ISA |
| X5 | `X5` | Packed RGB patch reuse using existing Xqmac8; no additional RTL |

X1/X2 in the main presentation mean the final tuned configuration. The old
folders named `X1` and `X2` retain their original meanings as initial instruction
checkpoints. D1 is retained as a measured ablation, even when the main X4 bar
groups its benefit with the new depthwise ISA.

```sh
gmake hardware-plan
gmake hardware-experiments
gmake submission-report
```

`gmake submission-package` additionally creates a local source/evidence archive
at `build/submission/arch-project-submission.tar.gz`, plus a SHA-256 checksum and
file manifest. It includes Git-visible sources, compact results, selected frozen
Spike captures, archived RTL snapshots and frozen B0 raw profiles. It excludes
toolchain/dependency installations, local access settings and unrelated ignored
files. Every compressed file is checked against its manifest before publication.
Native diagnostic build trees are regenerated separately when running the
software workflow after extraction.

`hardware-experiments` runs profiler, custom-ISA, compiler, monitor and offline
RTL overlay gates, revalidates retained captures against the explicit plans, and
generates [hardware results](../results/profiling/hardware-progression/README.md)
and [the unified package](../results/submission/README.md). Existing hardware
stage order is unchanged, so valid captures are reused; no capture is relabelled
as a fresh measurement. X2.2 has been measured through the production compiler,
replacing reliance on the older header-overlay prototype for the intermediate
outlining-only result.

The default runner can regenerate a missing stage on a clean checkout. It
creates a distinct `build/compiler/HW-<stage>` directory, runs native output,
intermediate arrays and sanitizers on all oracle cases, then ordinary Spike and
two identical full profiles, plus a second seed-42 RV64 output check. Use
`gmake hardware-recapture` to explicitly regenerate the complete sequence while
preserving historical evidence. A recapture must reproduce the retained
inference metrics. A complete report requires stages through X5.

`gmake hardware-checkpoints HARDWARE_THROUGH=X2.2` validates or generates a
prefix. `gmake hardware-report` requires a complete capture index and regenerates
only the report. `gmake hardware-tests` runs gates separately. Machine-readable
selected-summary pointers are in
`results/profiling/hardware-progression/captures.json`; partial or stale indexes
are rejected for final report generation.

Each frozen kernel plan is reconstructed from the production selector and the
manifest and must compare exactly. Saved summaries are regenerated from their
hash-verified raw captures. Historical reporter-version hashes can differ;
measurements, ELF identity, input, model, boundaries, node costs, footprint and
all other summary fields must match. Comparison edges and the original embedded
capture parent are both saved, so a derived D1 → X4 comparison does not rewrite
the historical X3-parent capture.

## RTL and cycle evidence

Full-model RTL cycles are retained for accepted B1, X1, X2, X3, X4 and X5.
The report checks archived PASS records, exact workload/ELF contracts, total and
per-opcode retirements, monitor gates and simulator identities. It decodes and
rehashes all 1,000 custom-stage output bytes from archived snapshots. Baseline
B1's snapshot retains the output hash/PASS record rather than the output bytes.
There is no separate full-model D1 cycle measurement; it remains unavailable.

Fresh Spike builds can change non-loaded debug metadata. Cycles always remain
bound to the exact archived RTL ELF; a fresh selected build must additionally
prove byte-for-byte equality of all loaded sections, addresses and segments
before those existing cycles can be compared. Matching instruction totals alone
is insufficient. X4 and X5 must retain the identical RTL configuration and
simulator binary, proving that X5 adds no hardware.

These commands revalidate existing RTL evidence. Full-model RTL reruns require
the pinned Linux/WSL environment; use
[the RTL guide](../docs/cvw-verilator.md#custom-instruction-full-inference) and
the existing extension-specific directed/replay commands. Collection remains
explicit through `tools/cvw/collect.py` and `collect_custom.py`, with their
matching workload contracts. A clean checkout needs regenerated or separately
supplied raw Spike captures and RTL snapshots before offline report validation.
The compact results and evidence hashes belong in Git; raw artifacts remain
under ignored `build/`.

Physical frequency, mapped area and speedup/area remain unavailable because
synthesis is blocked at DC startup. Simulated cycle speedup is reported
separately from instruction-count ratios and physical execution time.
